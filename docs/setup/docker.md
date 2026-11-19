# Docker deployment

Run Binderdash as a shared server with Docker Compose.

## Overview

The application is containerized using a single Docker image that:

- Builds the frontend (Vue.js + Vite) during the Docker build process
- Serves both the backend API and frontend static files via FastAPI
- Mounts data directories as read-only volumes for security
- Includes health checks and resource limits

For PAM authentication inside Docker (bind-mounting `/etc/passwd`/`/etc/group`/`/etc/shadow`, the `shadow` group requirement, and container-recreate gotchas), see [Authentication setup](authentication.md#auth-type-3-pam-usernamepassword-unix-accounts).

## Prerequisites

### Host Directory Setup

Before running the containerized application, ensure the directories specified in `RUN_BASE_DIRS` exist and are accessible on the host. They should contain your protein binder design run data; the container mounts them as read-only volumes.

```bash
# Example: make directories readable by the container user (see "Container user" below)
sudo chmod -R a+rX /data/runs /data2/runs
```

### Environment Configuration

1. Copy `.env.example` to `.env`:

   ```bash
   cp .env.example .env
   ```

2. Set the container user to your own uid and gid (see [Container user](#container-user)):

   ```bash
   printf 'BINDERDASH_UID=%s\nBINDERDASH_GID=%s\n' "$(id -u)" "$(id -g)" >> .env
   ```

3. Configure environment variables in `.env`:

   ```bash
   # Required: set the paths to your data directories
   RUN_BASE_DIRS="/data/runs,/data2/runs"

   # Optional: Google OAuth allowlist (use with GOOGLE_AUTH_* vars)
   GOOGLE_AUTH_ALLOWED_USERS="user1@example.com,user2@example.com"

   # Optional: for local authentication (dev only)
   LOCAL_USERS="alice:$2b$12$...,bob:$2b$12$..."
   ```

Docker Compose automatically loads all environment variables from the `.env` file.

### Mounting your run directories

Because Binderdash reads `RUN_BASE_DIRS` inside the container, mount each directory into the `binderdash` service and list its container path. For example, to serve runs from `/data/runs` on the host, add a volume to `docker-compose.yml`:

```yaml
services:
  binderdash:
    volumes:
      - /data/runs:/data/runs:ro
```

Then set `RUN_BASE_DIRS="/data/runs"` in `.env`. A read-only mount (`:ro`) works because Binderdash does not write to run folders.

### Database directory

Binderdash creates the SQLite database in `./data` on the host (mounted at `/app/data`) on first start. The `data/` directory is tracked in the repository, so it already exists after cloning and is owned by your user.

### Container user

The `binderdash` container runs as a non-root user configured by numeric IDs in `.env`:

| Variable | Meaning | Default |
| --- | --- | --- |
| `BINDERDASH_UID` | User ID the container process runs as | `1000` |
| `BINDERDASH_GID` | Group ID the container process runs as | `1000` |

This uid and gid own any files created in `./data` (the SQLite database and its `-wal`/`-shm` files) and need read access to your run directories. Matching your host user ensures:

- `./data`, which you own after cloning, is writable without a `chown`
- run directories you can read, the container can read
- the database files on the host belong to you, so you can back up, copy or delete them without `sudo`

To set them to the user you are logged in as:

```bash
printf 'BINDERDASH_UID=%s\nBINDERDASH_GID=%s\n' "$(id -u)" "$(id -g)" >> .env
```

This writes literal numbers such as `BINDERDASH_UID=1001` into `.env`. Do not use `$UID` or `$GID`: Compose only expands variables from its own environment, bash does not export `UID`, and bash defines no `GID` variable. Writing `$UID` in `.env` expands to an empty string, triggers a `"UID" variable is not set` warning, and defaults the container to `1000`.

Check the result with:

```bash
docker compose config | grep 'user:'
```

If you change the ids after the database exists, give `./data` to the new owner and recreate the container (`docker compose restart` keeps the old user):

```bash
sudo chown -R <uid>:<gid> data
docker compose up -d
```

The variables are read by Docker Compose only; the Binderdash backend ignores them. They apply to `docker-compose.dev.yml` too.

### HTTPS with Caddy

`docker-compose.yml` runs a [Caddy](https://caddyserver.com/) reverse proxy on ports 80 and 443 in front of Binderdash. Set `DOMAIN` in `.env` to the server's public hostname and Caddy obtains a TLS certificate automatically. With `DOMAIN` unset, Caddy serves `https://localhost` with a locally issued certificate. Also set `CORS_ALLOWED_ORIGINS` to your site URL, and set a fixed `SECRET_KEY` so sign-in sessions persist across restarts.

## Building and Running

### Production Mode

```bash
# Build the Docker image
docker compose build
# Or build with no cache (if you need a fresh build)
docker compose build --no-cache

# Start the application
docker compose up
# Run in detached mode
docker compose up -d
# View logs
docker compose logs -f
# Stop the application
docker compose down
```

Development with live reloading (`docker-compose.dev.yml`) is covered in [Development setup](../development/setup.md#docker-development-mode).

## Health Checks

The application includes health checks that verify the FastAPI server is responding on `/health`, run every 30 seconds with a 10-second timeout.

```bash
# View health status
docker compose ps

# Test health endpoint directly
curl http://localhost:8000/health
```

## Resource Limits

The container is configured with resource limits:

- Memory: 2GB limit, 512MB reservation
- CPU: 1.0 CPU limit, 0.5 CPU reservation

Adjust these in `docker-compose.yml` if needed for your environment.

## Security Considerations

1. Non-root user: the container runs as `BINDERDASH_UID`:`BINDERDASH_GID` (default 1000:1000), not root.
2. Read-only volumes: data directories are mounted read-only.
3. Environment variables: sensitive configuration is passed via environment variables instead of baking secrets into the image.
4. Network: only Caddy (ports 80 and 443) is exposed to the host; the Binderdash container listens on port 8000 on the internal Compose network.

## Troubleshooting

### Common Issues

1. Permission denied on data directories: the container user (see [Container user](#container-user)) must be able to read the run directories and write `./data`. Either set `BINDERDASH_UID`/`BINDERDASH_GID` to the owner, or make the directories readable:

   ```bash
   sudo chmod -R a+rX /data/runs /data2/runs
   ```

2. Container will not start:

   ```bash
   docker compose logs binderdash
   netstat -tulpn | grep :8000
   cat .env
   ```

3. Health check failing:

   ```bash
   curl -v http://localhost:8000/health
   docker compose logs -f binderdash
   ```

4. Frontend not loading:
   - Ensure the frontend was built during the Docker build process
   - Check that static files are being served correctly
   - Verify the build output in the container: `docker compose exec binderdash ls -la /app/backend/static/`

### Debugging

```bash
# Access the container shell
docker compose exec binderdash /bin/bash

# Check application status
docker compose exec binderdash ps aux
```

## Production Deployment

For production deployment:

1. Put a reverse proxy (nginx, traefik, or Caddy; see `Caddyfile` and `DOMAIN` in `.env.example`) in front of the container.
2. Terminate SSL/TLS at the reverse proxy.
3. Configure logging and log rotation.
4. Set up monitoring and alerting.
5. Manage sensitive environment variables with a secrets manager.
6. Consider Docker Swarm or Kubernetes for orchestration.

### Example nginx configuration

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Environment Variables Reference

| Variable                    | Description                                                       | Default                  | Required |
| --------------------------- | ------------------------------------------------------------------| ------------------------ | -------- |
| `RUN_BASE_DIRS`             | Comma-separated list of base directories to scan                  | `/data/runs,/data2/runs` | Yes      |
| `BINDERDASH_UID`            | Numeric uid the container runs as (see [Container user](#container-user)) | `1000`           | No       |
| `BINDERDASH_GID`            | Numeric gid the container runs as                                  | `1000`                   | No       |
| `GOOGLE_AUTH_ALLOWED_USERS` | Comma-separated allowed Google sign-in emails (with Google OAuth)  | Empty                    | No       |
| `LOCAL_USERS`               | Comma-separated list of local users with bcrypt hashes             | Empty                    | No       |
| `SECRET_KEY`                | JWT secret key (auto-generated if not provided)                    | Auto-generated           | No       |
| `CORS_ALLOWED_ORIGINS`      | Comma-separated list of allowed CORS origins                       | `*`                      | No       |
| `DISABLE_AUTHENTICATION`    | Set to `true` to disable all authentication                        | `false`                  | No       |

See `.env.example` for the full, current list of supported variables.
