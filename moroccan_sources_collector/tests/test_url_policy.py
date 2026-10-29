"""URL syntax and scope are checked before collection and export."""

import pytest

from src.validation.url_policy import is_regular_website_url, is_valid_web_url


@pytest.mark.parametrize(
    "url",
    [
        "https://example.ma/path?q=darija%26culture",
        "HTTP://www.example.ma:8080/",
        "https://example.ma./",
        "https://localhost/",
        "http://127.0.0.1:8000/",
        "https://[::1]:443/",
        "https://مثال.المغرب/",
    ],
)
def test_valid_absolute_web_urls(url):
    assert is_valid_web_url(url)
    assert is_regular_website_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "", "   ", None, 3,
        "https:///", "example.ma/path", "//example.ma/path", "ftp://example.ma/file",
        "https://example.ma:abc/", "https://example.ma:65536/", "https://example.ma:-1/",
        "https://example.ma:/", "https://[invalid]/", "https://example..ma/",
        "https://-example.ma/", "https://example.ma../", "https://exa%mple.ma/",
        "https://example.ma/a b", "https://example.ma/a\nb", "https://example.ma/a\tb",
        "https://example.ma/a\x00b", "https://example.ma/a\x7fb", "https://example.ma/a\\b",
    ],
)
def test_invalid_web_urls_are_outside_policy(url):
    assert not is_valid_web_url(url)
    assert not is_regular_website_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com/watch?v=1", "https://m.youtube.com:443/watch?v=1",
        "https://www.YouTube.com./watch?v=1", "https://youtu.be/1",
        "https://facebook.com/page", "https://fb.com/page", "https://fb.watch/1",
        "https://github.com/owner/repo", "https://api.github.com:443/repos/owner/repo",
        "https://huggingface.co/datasets", "https://kaggle.com/datasets",
        "https://user:password@github.com:443/owner/repo",
        "https://ｙｏｕｔｕｂｅ.com/watch?v=1", "https://youtube。com/watch?v=1",
    ],
)
def test_platform_host_is_excluded_independently_of_url_presentation(url):
    assert is_valid_web_url(url)
    assert not is_regular_website_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://notyoutube.com/", "https://youtube.com.example.ma/",
        "https://github.com.example.ma/", "https://mygithub.com/",
        "https://example.ma/article?source=https://github.com/owner/repo",
        "https://youtube.com@example.ma/",
    ],
)
def test_similar_or_mentioned_platform_names_do_not_exclude_another_host(url):
    assert is_regular_website_url(url)
