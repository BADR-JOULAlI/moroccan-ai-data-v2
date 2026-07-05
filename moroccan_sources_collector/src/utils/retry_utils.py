from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


def network_retry(max_attempts: int = 3):
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
