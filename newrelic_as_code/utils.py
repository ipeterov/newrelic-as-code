def echo(message: str, prefix: str = "->> ") -> None:
    """Print a message with a visible prefix.

    The prefix makes reconcile output easy to spot in CI logs.
    """
    print(f"{prefix}{message}", flush=True)  # noqa: T201
