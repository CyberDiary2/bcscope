# bcscope

scrapes in-scope URLs from a public Bugcrowd program page and saves them to a text file.

## install

```bash
git clone git@github.com:CyberDiary2/bcscope.git
cd bcscope
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# arch linux - do NOT use --with-deps (tries to run apt-get and will fail)
playwright install chromium

# other linux/mac
playwright install --with-deps chromium
```

## usage

```bash
# print scope to stdout
python bcscope.py https://bugcrowd.com/tesla

# save to file
python bcscope.py https://bugcrowd.com/tesla -o tesla_scope.txt

# pipe straight into dreakon
python bcscope.py https://bugcrowd.com/tesla -o scope.txt
dreakon scan tesla.com -i scope.txt

# pipe into stab
python bcscope.py https://bugcrowd.com/tesla -o scope.txt
stab scan tesla.com -i scope.txt
```

## how it works

1. tries Bugcrowd's JSON API endpoints first (fast, no browser needed)
2. falls back to Playwright headless browser if API fails - intercepts network responses and scrapes the rendered DOM
3. outputs one target per line (domains, wildcards, URLs)

## notes

- only works on public programs (no login required)
- private/invite-only programs will return no results
- some programs list wildcards like `*.tesla.com` - feed these directly into dreakon
