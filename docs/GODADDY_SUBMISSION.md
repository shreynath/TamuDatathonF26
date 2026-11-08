# GoDaddy Registry

The MLH campaign page for this prize is https://www.tech.study/ . That hostname is on `.study`, which is a GoDaddy Registry TLD. `.tech` is not treated as eligible by `sponsor_hub/godaddy.py`.

This repository does not register a domain, pay a registrar, or prove ownership. `prize_ready` stays false.

## Names worth checking

| Name | Why it is on the list |
|---|---|
| `gildedace.study` | The floor-review project, on the campaign TLD. |
| `pitboss.study` | The agent and the evidence assistant. |
| `evidencefirst.study` | The rule that code owns the figures. |

On November 7, 2026 a read-only query to `https://rdap.nic.study` returned HTTP 404 for `gildedace.study`, `pitboss.study`, and `evidencefirst.study`. None of the three resolved in DNS. That is a registry "not found" response, not a registration and not a hold. Availability can change. `prize_ready` stays false.

## Check a name

Syntax, TLD, and the blocker list, with no network:

```sh
python -m sponsor_hub.cli domain --value gildedace.study
```

DNS, HTTPS, and RDAP, only when you mean it:

```sh
python -m sponsor_hub.cli domain --live --value gildedace.study
```

The live command can contact the public DNS resolver and `https://rdap.org`. It does not send a registration.

## What a finished entry still needs

1. Register one `.study` name at a GoDaddy Registry registrar. You pay for it. Keep the receipt.
2. Point the name at a host you control and serve the floor page with a valid certificate.
3. Re-run the live check. Keep the JSON next to the receipt.
4. Put the hostname in the project description. Do not claim the prize from a DNS check alone.
