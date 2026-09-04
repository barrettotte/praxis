# Frontend

The browser application uses React, TypeScript, and Vite. Type-aware ESLint,
Prettier, Vitest, and Testing Library provide the frontend quality checks.

Use the repository-level Make targets for normal development:

```bash
make bootstrap
make dev-frontend
make check
make build
```

## Application user setup

OpenTofu creates an empty, admin-only Cognito user pool. Creating the single
application user is a manual AWS write and must not be added to OpenTofu because
temporary passwords do not belong in infrastructure state.

Run the following once for each newly deployed user pool, replacing the email
placeholder. Cognito sends the temporary password to that address:

```bash
PRAXIS_USER_EMAIL="you@example.com"
PRAXIS_USER_POOL_ID="$(AWS_PROFILE=praxis-dev tofu -chdir=infra/environments/dev output -raw cognito_user_pool_id)"

AWS_PROFILE=praxis-dev aws cognito-idp admin-create-user \
  --region us-east-1 \
  --user-pool-id "${PRAXIS_USER_POOL_ID}" \
  --username "${PRAXIS_USER_EMAIL}" \
  --user-attributes \
    Name=email,Value="${PRAXIS_USER_EMAIL}" \
    Name=email_verified,Value=true \
  --desired-delivery-mediums EMAIL
```

Do not store the temporary or permanent password in this repository, shell
configuration, or frontend environment files. Destroying the development stack
also removes this application user.

## Local authentication configuration

Copy `.env.example` to `.env` and populate its public Cognito and API values
from the development OpenTofu outputs:

```bash
cp frontend/.env.example frontend/.env
AWS_PROFILE=praxis-dev tofu -chdir=infra/environments/dev output -raw cognito_user_pool_id
AWS_PROFILE=praxis-dev tofu -chdir=infra/environments/dev output -raw cognito_frontend_client_id
AWS_PROFILE=praxis-dev tofu -chdir=infra/environments/dev output -raw api_gateway_url
```

Set those values as `VITE_COGNITO_USER_POOL_ID` and
`VITE_COGNITO_CLIENT_ID`, and `VITE_API_URL`, respectively. Start the application with
`make dev-frontend` and open exactly `http://localhost:5173`; the deployed CORS
policy intentionally rejects other hosts and ports. Sign in with the emailed
temporary password and choose a permanent password that satisfies the displayed
policy. Auth tokens use browser session storage and are cleared when the tab
closes or the user signs out.

Recommendation submission returns a pending session immediately. The browser
polls the authenticated session route for up to two minutes while retaining the
visible and assistive-technology progress state. Ready sessions render the
three validated candidates; failed or expired sessions show the fixed retryable
message without dependency details.

Selecting a candidate renders a feasibility-aware project brief with a concrete
technical approach, explicit assumptions and exclusions, deliverables,
self-service milestone verification, risks, and measurable acceptance checks.
The API derives the original goal, candidate, and evidence from the expiring
server session; the browser sends only the session and candidate identifiers.

## Deployed application

OpenTofu creates a private S3 origin and CloudFront distribution. After applying
the reviewed infrastructure plan, publish a production bundle explicitly:

```bash
make deploy-frontend-dev CONFIRM=deploy-frontend-dev
make smoke-dev SUITE=frontend
```

The deployment reads the non-secret API URL, Cognito pool ID, and Cognito client
ID from OpenTofu outputs, embeds them with Vite, synchronizes `frontend/dist/`,
and invalidates the distribution. It prints the deployed HTTPS URL. No `.env`
file is required for this production build, and no AWS credential is placed in
the browser bundle.
