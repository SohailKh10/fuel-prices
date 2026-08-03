# Pakistan Fuel Price Auto-Updater

Scrapes PSO's official fuel price page daily and keeps `rates.json` up to date,
so your website can fetch fresh petrol/diesel prices without you touching anything.

## One-time setup (5 minutes)

1. Create a **new GitHub repository** (public — private repos need a paid plan
   for scheduled Actions on personal accounts... actually public repos get
   free Actions minutes either way, public is simplest).
2. Upload all the files in this folder to that repo, keeping the folder
   structure (`.github/workflows/update-fuel-prices.yml` must stay in that
   exact path).
3. Go to your repo's **Actions** tab → you should see "Update Pakistan Fuel
   Prices" listed. Click it → **Run workflow** once, to test it manually.
4. Check that `rates.json` updated / committed correctly.
5. From now on, it runs automatically every night — no action needed from you.

## Using it on your website

Your `rates.json` will be publicly readable at:

```
https://raw.githubusercontent.com/<your-username>/<your-repo>/main/rates.json
```

In `rates.html`, replace the placeholder URL in the `FUEL_JSON_URL` constant
near the top of the script with that link. The page will then fetch live data
on every page load, and automatically falls back to the last-known static
table if the fetch ever fails (e.g. GitHub is briefly unreachable).

## If PSO changes their page layout

The scraper looks for the text `PREMIER EURO 5` and `HI-CETANE DIESEL EURO 5`
followed by a price. If PSO redesigns their site and this stops matching,
the GitHub Action will fail (you'll get an email from GitHub) — just let me
know and I'll update the scraper's selectors.
