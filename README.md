# Portal Check Alerts

Checks whether the **Staging** and **Dev** portals are reachable every 10 minutes via GitHub Actions. Sends an **alert email** on first failure and a **recovery email** when the portal comes back up. State is persisted in a private GitHub Gist so duplicate emails are never sent.