# Security policy

WorldClaw Studio is local-first. It binds to loopback by default. Do not expose
it to a network without configuring `WORLDCLAW_API_TOKEN`; generation jobs can
start local processes and read artifacts from the configured job directory.

Do not include secrets in issues. Report path traversal, command execution,
authentication bypass, unsafe archive extraction, or dependency vulnerabilities
privately through the repository's GitHub security advisory interface.

Only the newest tagged release receives security fixes during the alpha phase.
