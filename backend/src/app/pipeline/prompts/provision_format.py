def format_provision(ref: str, header: str, body: str) -> str:
    return f'<provision ref="{ref}">\n{header}\n\n{body}\n</provision>'
