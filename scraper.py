"""
Sjekker Finn.no for kortsamlinger. Denne filen er laget for å kjøres ÉN
gang per kjøring (av GitHub Actions), ikke som en evigvarende loop slik
den opprinnelige finn_watcher.py gjorde på en lokal PC.

Leser og skriver:
  - funn.json               -> det nettsiden viser
  - data/sett_annonser.json -> hvilke annonser vi allerede har vurdert
"""

import re
import os
import json
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

# ---------- Innstillinger ----------
FINN_URLS = [
    "https://www.finn.no/recommerce/forsale/search?product_category=2.86.285.396&sort=PUBLISHED_DESC"
]
MAKS_PRIS = 500
STIKKORD = [
    "samling", "bunke", "eske", "permer", "album",
    "masse", "parti", "større", "flyttesalg", "kortsamling"
]
MAKS_FUNN_LAGRET = 100      # hvor mange funn som vises på siden
MAKS_ID_LAGRET = 5000       # hvor mange annonse-ID-er vi husker (for å unngå at filen vokser evig)

FUNN_FIL = "funn.json"
SETT_FIL = "data/sett_annonser.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "no-NO,no;q=0.9,en-US;q=0.8,en;q=0.7",
}

ITEM_LENKE_MØNSTER = re.compile(r"/recommerce/forsale/item/(\d+)")
PRIS_MØNSTER = re.compile(r"([\d\s\u00a0.]{1,10})\s*kr\b", re.IGNORECASE)


def les_json(sti, standard):
    try:
        with open(sti, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return standard


def lagre_json(sti, data):
    mappe = os.path.dirname(sti)
    if mappe:
        os.makedirs(mappe, exist_ok=True)
    with open(sti, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def hent_side_med_retry(url, forsok=3):
    for i in range(1, forsok + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                return r
            print(f"Fikk statuskode {r.status_code} (forsøk {i}/{forsok})")
        except requests.RequestException as e:
            print(f"Nettverksfeil: {e} (forsøk {i}/{forsok})")
        if i < forsok:
            time.sleep(5 * i)
    return None


def finn_annonse_kort(soup):
    kort = {}
    for anker in soup.find_all("a", href=ITEM_LENKE_MØNSTER):
        treff = ITEM_LENKE_MØNSTER.search(anker["href"])
        if not treff:
            continue
        annonse_id = treff.group(1)
        if annonse_id in kort:
            continue

        container = anker
        for _ in range(8):
            if container.parent is None:
                break
            container = container.parent
            if container.find("h2"):
                break

        overskrift = container.find("h2")
        tittel = overskrift.get_text(strip=True) if overskrift else "Ukjent tittel (se lenke)"
        full_tekst = container.get_text(separator=" ", strip=True)

        pris = None
        pris_treff = PRIS_MØNSTER.search(full_tekst)
        if pris_treff:
            siffer = re.sub(r"[\s\u00a0.]", "", pris_treff.group(1))
            if siffer.isdigit():
                pris = int(siffer)

        kort[annonse_id] = {
            "id": annonse_id,
            "lenke": f"https://www.finn.no/recommerce/forsale/item/{annonse_id}",
            "tittel": tittel,
            "pris": pris,
            "tekst": full_tekst.lower(),
        }
    return list(kort.values())


def inneholder_stikkord(tekst):
    return any(s in tekst for s in STIKKORD)


def main():
    sett_annonser = set(les_json(SETT_FIL, []))
    forste_kjoring = len(sett_annonser) == 0
    funn_data = les_json(FUNN_FIL, {"sist_sjekket": None, "funn": []})

    if forste_kjoring:
        print("Første kjøring: lagrer eksisterende annonser uten å varsle om dem.")

    for url in FINN_URLS:
        respons = hent_side_med_retry(url)
        if respons is None:
            print(f"Ga opp å hente siden: {url}")
            continue

        soup = BeautifulSoup(respons.text, "html.parser")
        annonser = finn_annonse_kort(soup)
        print(f"Fant {len(annonser)} annonser på siden.")

        for annonse in annonser:
            if annonse["id"] in sett_annonser:
                continue

            if not forste_kjoring:
                har_stikkord = inneholder_stikkord(annonse["tekst"])
                pris = annonse["pris"]
                innenfor_budsjett = pris is None or pris <= MAKS_PRIS

                if har_stikkord and innenfor_budsjett:
                    print(f"MATCH: {annonse['tittel']} ({pris} kr)")
                    funn_data["funn"].insert(0, {
                        "tittel": annonse["tittel"],
                        "pris": pris,
                        "lenke": annonse["lenke"],
                        "funnet": datetime.now(timezone.utc).isoformat(),
                    })

            sett_annonser.add(annonse["id"])

    # Behold bare de nyeste funnene og ID-ene, så filene ikke vokser i det uendelige
    funn_data["funn"] = funn_data["funn"][:MAKS_FUNN_LAGRET]
    if len(sett_annonser) > MAKS_ID_LAGRET:
        sett_annonser = set(sorted(sett_annonser, key=int)[-MAKS_ID_LAGRET:])

    funn_data["sist_sjekket"] = datetime.now(timezone.utc).isoformat()

    lagre_json(FUNN_FIL, funn_data)
    lagre_json(SETT_FIL, sorted(sett_annonser, key=int))

    print("Ferdig.")


if __name__ == "__main__":
    main()
