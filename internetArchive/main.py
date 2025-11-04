from typing import List
from settings import (
    CORE_API_HOST,
    INTERNET_ARCHIVE_TOKENS,
    ADDITIONAL_SAVE_HOSTS,
    MAX_REQUESTS_PER_WINDOW,
    WINDOW_SECONDS,
)
import requests
import logging
from typing import TypedDict
from itertools import cycle
import time
import json
import random
from collections import deque

logger = logging.getLogger(__name__)


class Organization(TypedDict):
    id: str
    description: str
    website: str


def get_org_infos() -> list[Organization]:
    url = f"{CORE_API_HOST}/api/v1/organizations"
    response = requests.get(url=url)
    response.raise_for_status()
    return response.json()


def submit_to_internet_archive(url: str, auth_header: dict) -> dict:
    """
    Submit a single URL to Internet Archive's Save Page Now 2 API (ONE attempt).

    Args:
        url: The website URL to archive
        auth_header: Dictionary containing authorization header

    Returns:
        Response from the API as a dictionary, or an error dictionary.
    """
    api_endpoint = "https://web.archive.org/save"

    try:
        response = requests.post(
            api_endpoint,
            headers=auth_header,
            data={"url": url, "capture_all": "1"},
            timeout=30,
        )
        response.raise_for_status()  # Raises HTTPError for 4xx/5xx

        # HTTP success (2xx)
        try:
            result = response.json()
            logger.info(f"Successfully submitted {url}")
            return result
        except json.JSONDecodeError:
            return {
                "error": "parse_error",
                "url": url,
                "status_code": response.status_code,
            }

    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code
        if status_code == 429:
            logger.warning(f"Rate limited (429) for {url}")
            return {"error": "rate_limited", "status_code": status_code, "url": url}
        elif status_code >= 500:
            logger.error(f"Server error {status_code} for {url}: {str(e)}")
            return {"error": "server_error", "status_code": status_code, "url": url}
        else:  # Other 4xx errors (e.g., 404)
            logger.error(f"HTTP error {status_code} for {url}: {str(e)}")
            return {"error": "http_error", "status_code": status_code, "url": url}

    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        # Handle connection refused, timeouts, etc.
        logger.warning(f"Connection/Timeout error for {url}: {str(e)}")
        return {"error": "connection_error", "details": str(e), "url": url}

    except requests.exceptions.RequestException as e:
        # Catchall for other request exceptions
        logger.error(f"Failed to submit {url}: {str(e)}")
        return {"error": "unknown_request_error", "details": str(e), "url": url}


def get_token_cycle(tokens: List[str]):
    """
    Create a cycle iterator from the list of tokens for load balancing.

    Args:
        tokens: List of authorization tokens (key:value format)

    Returns:
        cycle iterator of authorization headers
    """
    auth_headers = [
        {"Authorization": f"LOW {token}", "Accept": "application/json"}
        for token in tokens
    ]
    return cycle(auth_headers)


def calculate_backoff_delay(base_delay: float, attempt_number: int) -> float:
    """
    Calculate exponential backoff delay based on attempt number.

    Args:
        base_delay: Base delay in seconds
        attempt_number: The attempt number (e.g., 0, 1, 2)

    Returns:
        Delay in seconds (capped at 60 seconds) with jitter
    """
    delay = base_delay * (2**attempt_number)
    # Add random jitter to prevent thundering herd
    return min(delay, 60.0) + random.uniform(0, 0.5)


def scrape_sites(tokens: List[str], additional_hosts: List[str]) -> int:
    """
    Fetch organization websites and submit them to Internet Archive.
    """
    logger.info("Getting org info")
    infos = get_org_infos()
    orgs_with_websites = list(
        filter(lambda x: x.get("website", None) is not None, infos)
    )
    logger.info(f"Found {len(orgs_with_websites)} orgs with websites")
    all_websites = list(map(lambda x: x["website"], orgs_with_websites))
    all_websites.extend(additional_hosts)
    logger.info(f"Total {len(all_websites)} websites to save")

    request_timestamps = deque()

    token_cycle = get_token_cycle(tokens)
    results = []

    base_retry_delay = 10.0  # Wait 10s *before a retry*
    consecutive_failures = 0
    max_retries_per_url = 3
    # --------------------------------------------------

    for website in all_websites:
        current_time = time.monotonic()

        # 1. Clear out any timestamps older than the window
        while request_timestamps and request_timestamps[0] <= (
            current_time - WINDOW_SECONDS
        ):
            request_timestamps.popleft()

        if len(request_timestamps) >= MAX_REQUESTS_PER_WINDOW:
            # We are at the limit. We must wait for the *oldest* request to fall out
            # of the window.
            oldest_request_time = request_timestamps[0]
            time_to_wait = (oldest_request_time + WINDOW_SECONDS) - current_time

            if time_to_wait > 0:
                logger.info(
                    f"Rate limit window full ({MAX_REQUESTS_PER_WINDOW} reqs). "
                    f"Waiting {time_to_wait:.1f}s..."
                )
                time.sleep(time_to_wait)

            request_timestamps.popleft()

        request_timestamps.append(time.monotonic())

        auth_header = next(token_cycle)

        for attempt in range(max_retries_per_url):
            result = submit_to_internet_archive(website, auth_header)
            error = result.get("error")

            if not error:
                results.append(result)
                if consecutive_failures > 0:
                    logger.info("Success. Resetting consecutive failure count.")
                consecutive_failures = 0
                break

            # --- Retryable Error ---
            if error in ("rate_limited", "connection_error", "server_error"):
                consecutive_failures += 1
                retry_delay = calculate_backoff_delay(
                    base_retry_delay, (attempt + consecutive_failures // 2)
                )
                logger.warning(
                    f"Error '{error}' for {website}. Attempt {attempt + 1}/{max_retries_per_url}. "
                    f"Retrying in {retry_delay:.1f}s..."
                )

                if attempt == max_retries_per_url - 1:
                    logger.error(
                        f"Failed to submit {website} after {max_retries_per_url} attempts."
                    )
                    results.append(result)
                else:
                    time.sleep(retry_delay)

                    current_time = time.monotonic()
                    while request_timestamps and request_timestamps[0] <= (
                        current_time - WINDOW_SECONDS
                    ):
                        request_timestamps.popleft()

                    if len(request_timestamps) >= MAX_REQUESTS_PER_WINDOW:
                        oldest_request_time = request_timestamps[0]
                        time_to_wait = (
                            oldest_request_time + WINDOW_SECONDS
                        ) - current_time
                        if time_to_wait > 0:
                            logger.info(
                                f"Rate limit window full (in retry). Waiting {time_to_wait:.1f}s..."
                            )
                            time.sleep(time_to_wait)
                        request_timestamps.popleft()

                    # Add timestamp for this *retry* attempt
                    request_timestamps.append(time.monotonic())
                    auth_header = next(token_cycle)  # Get a fresh token

            else:
                # --- Permanent Error (e.g., http_error 404) ---
                logger.error(f"Permanent error '{error}' for {website}. Not retrying.")
                results.append(result)
                break  # Break retry loop, move to next website

    # --- Count final results ---
    error_count = sum(1 for r in results if "error" in r)
    successful = len(all_websites) - error_count
    rate_limited_failures = sum(1 for r in results if r.get("error") == "rate_limited")

    logger.info(f"Completed: {successful}/{len(all_websites)} successful submissions")
    logger.info(
        f"Errors: {error_count} (including {rate_limited_failures} final rate-limit failures)"
    )

    return error_count


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    exit_code = scrape_sites(INTERNET_ARCHIVE_TOKENS, ADDITIONAL_SAVE_HOSTS)
    exit(exit_code)
