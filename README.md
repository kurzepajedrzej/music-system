# music-system

Merged Python backend (FastAPI) and React + TypeScript + Vite frontend for
the home music system — replaces `music-backend`, `cd-control`, and
`music-frontend`. See `backend/README.md` and `frontend/README.md` for each
half.

This repo deploys independently, with its own `docker-compose.yml`,
`startup.sh`, and `systemd/music-system.service`. See this repo's own
`CLAUDE.md` for the full architecture, deployment, and troubleshooting
details, and `../homelab-configs/CLAUDE.md` for how this fits into the
wider server.
