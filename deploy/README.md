# Vultr production deployment checklist

The bridge changes the existing server to default to `127.0.0.1:8765` but respect
`PITBOSS_HOST`/`PITBOSS_PORT`. This Dockerfile opts into `0.0.0.0` **inside the
container only**. Do not publish the port on the public Internet directly. Deploy
behind HTTPS and restrict unauthenticated traffic. The bridge also gates the
original `/api/investigate` paid Gemini narrative on the private sponsor token.

Do not provision a paid Vultr instance automatically. Require the account owner to
approve region, compute size, network, budget, and API scopes. Set
`SPONSOR_API_TOKEN` and provider keys in an environment/secret manager, not the image.

Verify external HTTPS, origin policy, authentication, rate limit, cost ceiling,
backend restart, and cold-start behavior. The static GitHub Pages deployment does
not automatically reach this same-origin private API. Do not embed the token in
public HTML. Provide a private judge demonstration or implement real user auth.

A successful read-only `python -m sponsor_hub.cli vultr --live` call only verifies
Vultr API access; it does NOT prove that the application is deployed there.
