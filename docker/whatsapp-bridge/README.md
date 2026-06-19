# WhatsApp bridge — SOURCE MIRROR (not a deployment)

This folder is a **version-controlled backup** of the WhatsApp bridge source
(`server.js`, `Dockerfile`, `package.json`). It is NOT meant to be run from here.

The **live deployment** is:  `~/whatsapp-baileys/`
(compose project `whatsapp-baileys`, container `whatsapp-baileys-whatsapp-1`).

The compose file here is renamed `docker-compose.yml.reference` on purpose, so
`docker compose up` won't accidentally spin up a SECOND bridge that fights the
real one for port 3001 and the shared WhatsApp session (this already happened
once — June 2026). To redeploy, copy the source into `~/whatsapp-baileys/` and
run compose there.
