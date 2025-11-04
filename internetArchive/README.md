# Internet Archive

This script calls the [ACM @ UIUC Core API](https://github.com/acm-uiuc/core), gets a list of all SIG/Committee websites, and submits them to the Internet Archive [SavePageNow 2 API](https://docs.google.com/document/d/1Nsv52MvSjbLb2PCpHlat0gkzw0EvtSgpKHu4mk0MnrA/view) for storage.

# Getting Started
Create a `.env` file with the following contents:
```bash
INTERNET_ARCHIVE_TOKENS="" # comma-seperated list of s3accesskey:s3secretkey for Internet Archive S3-like API
ADDITIONAL_HOSTS="" # comma seperated list of additional hosts to request saving for
```
This script uses the `uv` package manager. Run `uv sync` and then `uv run main.py`

Note that the Wayback Machine rate limiting is **very aggressive** and will IP-ban you for sending more than 15 requests every minute.

We use two client IDs but it's unclear if that helps. VPNs are also usually getting 429'ed as well. So be careful and don't run this script too many times!