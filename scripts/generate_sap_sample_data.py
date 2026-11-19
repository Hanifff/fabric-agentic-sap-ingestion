#!/usr/bin/env python3
"""Generate synthetic SAP S/4HANA-style extracts for the demo.

The company ("Contoso Drilling Systems") and all records are fictional. Output is
deterministic (fixed seed), so re-running produces identical files.

Layout: data/sap_s4/<TABLE>/load_date=YYYY-MM-DD/<TABLE>_YYYYMMDD.csv

- Master data (T001W, MARA, MAKT, LFA1, KNA1): one full snapshot per load date.
- Transactions (EKKO, EKPO, VBAK, VBAP, MATDOC): only records created or changed on
  that day, flagged with ODQ_CHANGEMODE (C = create, U = update) like an ODP delta.
"""
import csv
import datetime as dt
import pathlib
import random
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "sap_s4"
LOAD_DATES = [dt.date(2026, 11, 12) + dt.timedelta(days=i) for i in range(7)]
MANDT = "100"
rng = random.Random(20261119)

PLANTS = [
    # WERKS, NAME1, LAND1, ORT01, BUKRS, WAERS
    ("US10", "Houston Manufacturing", "US", "HOUSTON", "1000", "USD"),
    ("US20", "Tulsa Service Center", "US", "TULSA", "1000", "USD"),
    ("DE10", "Hamburg Manufacturing", "DE", "HAMBURG", "2000", "EUR"),
    ("GB10", "Aberdeen Service Center", "GB", "ABERDEEN", "3000", "GBP"),
    ("SG10", "Singapore Service Center", "SG", "SINGAPORE", "4000", "SGD"),
]
PURCH_ORG = {"1000": "1000", "2000": "2000", "3000": "3000", "4000": "4000"}
SALES_ORG = {"1000": "1000", "2000": "2000", "3000": "3000", "4000": "4000"}
CURRENCY = {p[4]: p[5] for p in PLANTS}
USERS = ["JSMITH", "KMUELLER", "AJONES", "MBROWN", "LTAN", "BATCH_MM", "BATCH_SD"]

MATERIAL_FAMILIES = [
    # MTART, MATKL, MEINS, price range, (name templates)
    ("FERT", "DRL-EQ", "EA", (250000, 2500000), ["Top Drive TD-{n}", "Iron Roughneck IR-{n}", "Drawworks DW-{n}",
                                                  "Mud Pump MP-{n}", "Pipe Handler PH-{n}", "Drill Floor Crane DFC-{n}"]),
    ("HALB", "DRL-SUB", "EA", (15000, 180000), ["Gearbox Assembly GB-{n}", "Hydraulic Power Unit HPU-{n}",
                                                 "Control Cabinet CC-{n}", "AC Motor Assembly MA-{n}"]),
    ("ROH", "RAW-STL", "KG", (4, 40), ["Steel Forging 42CrMo4 Grade {n}", "Bearing Steel Bar 100Cr6 D{n}"]),
    ("ROH", "RAW-HYD", "M", (20, 300), ["Hydraulic Hose 1in R{n}", "Hydraulic Tube 25mm S{n}"]),
    ("ROH", "RAW-ELE", "M", (10, 220), ["Power Cable 3x95 T{n}", "Signal Cable 12x0.75 T{n}"]),
    ("ERSA", "SPR-MECH", "EA", (200, 25000), ["Seal Kit SK-{n}", "Roller Bearing RB-{n}", "Brake Pad BP-{n}",
                                               "Wash Pipe Assembly WP-{n}", "Swivel Packing SP-{n}"]),
    ("ERSA", "SPR-HYD", "EA", (300, 18000), ["Valve Insert VI-{n}", "Hydraulic Cylinder HC-{n}"]),
    ("ERSA", "SPR-ELEC", "EA", (150, 9000), ["Pressure Sensor PS-{n}", "Encoder EN-{n}", "PLC IO Module IO-{n}"]),
]
VENDOR_PREFIX = ["Northern", "Rhine", "Hanse", "Alpine", "Gulf Coast", "Lone Star", "Bayou", "Granite",
                 "Highland", "Clyde", "Pacific", "Lion City", "Atlas", "Titan", "Summit", "Harbor"]
VENDOR_SUFFIX = ["Forge", "Hydraulics", "Castings", "Machining", "Seals", "Bearings", "Electro", "Steel",
                 "Valves", "Fasteners", "Automation", "Cables"]
LEGAL = {"NL": "BV", "US": "LLC", "GB": "Ltd", "SG": "Pte Ltd", "DE": "GmbH"}
CITIES = {"NL": ["ROTTERDAM", "DEN HELDER"], "US": ["HOUSTON", "TULSA", "DALLAS"],
          "GB": ["ABERDEEN", "GLASGOW"], "SG": ["SINGAPORE"], "DE": ["HAMBURG", "BREMEN"]}
CUSTOMER_NAMES = ["North Sea Drilling", "Arctic Rig Operations", "Gulf Offshore Drilling", "Deepwater Pioneer",
                  "Caspian Energy Services", "Atlantic Jackup", "Pelican Rig Services", "Coral Sea Drilling",
                  "Ironclad Offshore", "Meridian Rig Partners", "Polar Star Drilling", "Southern Cross Offshore",
                  "Blue Whale Drilling", "Granite Shelf Operations", "Kraken Subsea", "Westwind Rigs"]


def d8(day: dt.date) -> str:
    return day.strftime("%Y%m%d")


def extract_ts(day: dt.date) -> str:
    # Extracts run at 02:15 UTC the morning after the business day they cover.
    return (dt.datetime.combine(day, dt.time(2, 15)) + dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def matnr(n: int) -> str:
    return f"{n:018d}"


# ----------------------------------------------------------------------------- master data
def build_materials():
    mats = []
    n = 10000100
    for mtart, matkl, meins, (lo, hi), names in MATERIAL_FAMILIES:
        count = {"FERT": 24, "HALB": 36, "ROH": 30, "ERSA": 75}[mtart] // (2 if mtart in ("ROH", "ERSA") else 1)
        for _ in range(count):
            n += rng.randint(1, 9)
            created = dt.date(2019, 1, 1) + dt.timedelta(days=rng.randint(0, 2400))
            name = rng.choice(names).format(n=rng.randint(100, 999))
            mats.append({
                "MATNR": matnr(n), "ERSDA": created, "ERNAM": rng.choice(USERS[:5]), "LAEDA": created,
                "AENAM": "", "MTART": mtart, "MBRSH": "M", "MATKL": matkl, "MEINS": meins,
                "BRGEW": round(rng.uniform(0.2, 40000) if mtart in ("FERT", "HALB") else rng.uniform(0.05, 250), 3),
                "GEWEI": "KG", "LVORM": "", "MAKTX": name, "PRICE": round(rng.uniform(lo, hi), 2),
            })
    return mats


def build_partners(kind: str, count: int, start: int, first_day: dt.date):
    rows = []
    for i in range(count):
        land = rng.choice(["US", "US", "DE", "DE", "GB", "SG", "NL"])
        if kind == "vendor":
            name = f"{rng.choice(VENDOR_PREFIX)} {rng.choice(VENDOR_SUFFIX)} {LEGAL[land]}"
            key = f"{start + i:010d}"
        else:
            name = f"{CUSTOMER_NAMES[i % len(CUSTOMER_NAMES)]} {LEGAL[land]}"
            key = f"{start + i:010d}"
        rows.append({"KEY": key, "LAND1": land, "NAME1": name, "ORT01": rng.choice(CITIES[land]),
                     "PSTLZ": f"{rng.randint(1000, 99999)}", "ERDAT": first_day - dt.timedelta(days=rng.randint(30, 2500)),
                     "ERNAM": rng.choice(USERS[:5]), "LOEVM": "", "SPERR": ""})
    return rows


# ----------------------------------------------------------------------------- writers
def write(table: str, day: dt.date, header: list, rows: list):
    folder = OUT / table / f"load_date={day.isoformat()}"
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / f"{table}_{d8(day)}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    materials = build_materials()
    vendors = build_partners("vendor", 48, 300000, LOAD_DATES[0])
    customers = build_partners("customer", 16, 500000, LOAD_DATES[0])
    po_counter, so_counter, doc_counter = 4500018200, 120004100, 5000310000
    open_pos, open_sos = [], []  # for later updates and goods movements

    for day in LOAD_DATES:
        ts = extract_ts(day)

        # --- master data changes during the day, then full snapshots
        for m in rng.sample(materials, 4):
            m["LAEDA"], m["AENAM"] = day, rng.choice(USERS[:5])
            m["BRGEW"] = round(m["BRGEW"] * rng.uniform(0.97, 1.03), 3)
        if day.weekday() < 5:
            for _ in range(rng.randint(1, 3)):
                base = int(materials[-1]["MATNR"]) + rng.randint(1, 9)
                fam = rng.choice(MATERIAL_FAMILIES)
                materials.append({"MATNR": matnr(base), "ERSDA": day, "ERNAM": rng.choice(USERS[:5]), "LAEDA": day,
                                  "AENAM": "", "MTART": fam[0], "MBRSH": "M", "MATKL": fam[1], "MEINS": fam[2],
                                  "BRGEW": round(rng.uniform(0.1, 500), 3), "GEWEI": "KG", "LVORM": "",
                                  "MAKTX": rng.choice(fam[4]).format(n=rng.randint(100, 999)),
                                  "PRICE": round(rng.uniform(*fam[3]), 2)})
        if day == LOAD_DATES[3]:
            materials[5]["LVORM"] = "X"  # flagged for deletion mid-week

        write("T001W", day, ["MANDT", "WERKS", "NAME1", "BWKEY", "LAND1", "ORT01", "SPRAS", "_EXTRACT_TS"],
              [[MANDT, p[0], p[1], p[0], p[2], p[3], "E", ts] for p in PLANTS])
        write("MARA", day, ["MANDT", "MATNR", "ERSDA", "ERNAM", "LAEDA", "AENAM", "MTART", "MBRSH", "MATKL",
                            "MEINS", "BRGEW", "GEWEI", "LVORM", "_EXTRACT_TS"],
              [[MANDT, m["MATNR"], d8(m["ERSDA"]), m["ERNAM"], d8(m["LAEDA"]), m["AENAM"], m["MTART"], m["MBRSH"],
                m["MATKL"], m["MEINS"], f'{m["BRGEW"]:.3f}', m["GEWEI"], m["LVORM"], ts] for m in materials])
        write("MAKT", day, ["MANDT", "MATNR", "SPRAS", "MAKTX", "MAKTG", "_EXTRACT_TS"],
              [[MANDT, m["MATNR"], lang, m["MAKTX"] if lang == "E" else m["MAKTX"].replace("Assembly", "Baugruppe"),
                m["MAKTX"].upper(), ts] for m in materials for lang in ("E", "D")])
        if day == LOAD_DATES[2]:
            vendors.append({"KEY": f"{300000 + len(vendors):010d}", "LAND1": "DE", "NAME1": "Hanse Additive GmbH",
                            "ORT01": "HAMBURG", "PSTLZ": "20095", "ERDAT": day, "ERNAM": "AJONES", "LOEVM": "", "SPERR": ""})
        if day == LOAD_DATES[4]:
            vendors[7]["SPERR"] = "X"  # purchasing block set
        write("LFA1", day, ["MANDT", "LIFNR", "LAND1", "NAME1", "ORT01", "PSTLZ", "KTOKK", "ERDAT", "ERNAM",
                            "SPERR", "LOEVM", "_EXTRACT_TS"],
              [[MANDT, v["KEY"], v["LAND1"], v["NAME1"], v["ORT01"], v["PSTLZ"], "KRED", d8(v["ERDAT"]),
                v["ERNAM"], v["SPERR"], v["LOEVM"], ts] for v in vendors])
        write("KNA1", day, ["MANDT", "KUNNR", "LAND1", "NAME1", "ORT01", "PSTLZ", "KTOKD", "BRSCH", "ERDAT",
                            "ERNAM", "LOEVM", "_EXTRACT_TS"],
              [[MANDT, c["KEY"], c["LAND1"], c["NAME1"], c["ORT01"], c["PSTLZ"], "KUNA", "OILG", d8(c["ERDAT"]),
                c["ERNAM"], c["LOEVM"], ts] for c in customers])

        # --- purchasing: new POs (fewer at weekends) plus updates to earlier POs
        ekko, ekpo = [], []
        business_day = day.weekday() < 5
        for _ in range(rng.randint(18, 30) if business_day else rng.randint(0, 3)):
            po_counter += 1
            plant = rng.choice(PLANTS)
            vendor = rng.choice(vendors)
            items = []
            for pos in range(1, rng.randint(1, 5) + 1):
                m = rng.choice([x for x in materials if x["MTART"] in ("ROH", "ERSA", "HALB")])
                qty = rng.randint(1, 40) if m["MEINS"] == "EA" else rng.randint(50, 2000)
                price = m["PRICE"]
                items.append([MANDT, str(po_counter), f"{pos * 10:05d}", "", d8(day), m["MATNR"], plant[0], "0001",
                              m["MATKL"], f"{qty:.3f}", m["MEINS"], f"{price:.2f}", "1", f"{qty * price:.2f}", "",
                              "C", ts])
            ekko.append([MANDT, str(po_counter), plant[4], "F", rng.choice(["NB", "NB", "NB", "FO"]), "", d8(day),
                         rng.choice(USERS[:5]), vendor["KEY"], PURCH_ORG[plant[4]], f"P{rng.randint(1, 4):02d}",
                         CURRENCY[plant[4]], d8(day), "C", ts])
            ekpo.extend(items)
            open_pos.append((str(po_counter), plant, items))
        earlier_pos = open_pos[:len(open_pos) - len(ekko)]
        for po, plant, items in rng.sample(earlier_pos, min(len(earlier_pos) // 6, 8)):
            item = list(rng.choice(items))
            item[4], item[14] = d8(day), "X"  # AEDAT changed, ELIKZ: delivery completed
            item[15], item[16] = "U", ts
            ekpo.append(item)
        write("EKKO", day, ["MANDT", "EBELN", "BUKRS", "BSTYP", "BSART", "LOEKZ", "AEDAT", "ERNAM", "LIFNR",
                            "EKORG", "EKGRP", "WAERS", "BEDAT", "ODQ_CHANGEMODE", "_EXTRACT_TS"], ekko)
        write("EKPO", day, ["MANDT", "EBELN", "EBELP", "LOEKZ", "AEDAT", "MATNR", "WERKS", "LGORT", "MATKL",
                            "MENGE", "MEINS", "NETPR", "PEINH", "NETWR", "ELIKZ", "ODQ_CHANGEMODE", "_EXTRACT_TS"], ekpo)

        # --- sales: equipment orders and spare-part orders
        vbak, vbap = [], []
        for _ in range(rng.randint(6, 14) if business_day else rng.randint(0, 2)):
            so_counter += 1
            plant = rng.choice(PLANTS)
            cust = rng.choice(customers)
            spare = rng.random() < 0.75
            total, items = 0.0, []
            for pos in range(1, (rng.randint(1, 6) if spare else 1) + 1):
                m = rng.choice([x for x in materials if x["MTART"] == ("ERSA" if spare else "FERT")])
                qty = rng.randint(1, 20) if spare else 1
                value = round(qty * m["PRICE"] * rng.uniform(1.15, 1.45), 2)
                total += value
                items.append([MANDT, str(so_counter), f"{pos * 10:06d}", m["MATNR"], m["MAKTX"], f"{qty:.3f}", "EA",
                              f"{value:.2f}", CURRENCY[plant[4]], plant[0], d8(day), d8(day), "", "C", ts])
            vbak.append([MANDT, str(so_counter), d8(day), f"{rng.randint(7, 17):02d}{rng.randint(0, 59):02d}00",
                         rng.choice(USERS[3:5]), "ZSP" if spare else "ZEQ", SALES_ORG[plant[4]], "10", "00",
                         cust["KEY"], f"{total:.2f}", CURRENCY[plant[4]], d8(day), "C", ts])
            vbap.extend(items)
            open_sos.append((str(so_counter), plant, items))
        earlier_sos = open_sos[:len(open_sos) - len(vbak)]
        if business_day and earlier_sos:
            so, plant, items = rng.choice(earlier_sos)
            item = list(items[0])
            item[12], item[11], item[13], item[14] = "Z1", d8(day), "U", ts  # ABGRU: rejected by customer
            vbap.append(item)
        write("VBAK", day, ["MANDT", "VBELN", "ERDAT", "ERZET", "ERNAM", "AUART", "VKORG", "VTWEG", "SPART",
                            "KUNNR", "NETWR", "WAERK", "AEDAT", "ODQ_CHANGEMODE", "_EXTRACT_TS"], vbak)
        write("VBAP", day, ["MANDT", "VBELN", "POSNR", "MATNR", "ARKTX", "KWMENG", "VRKME", "NETWR", "WAERK",
                            "WERKS", "ERDAT", "AEDAT", "ABGRU", "ODQ_CHANGEMODE", "_EXTRACT_TS"], vbap)

        # --- inventory movements: goods receipts for earlier POs, issues for sales orders
        matdoc = []
        if business_day:
            year = str(day.year)
            for po, plant, items in rng.sample(open_pos, min(len(open_pos), rng.randint(10, 20))):
                doc_counter += 1
                for line, item in enumerate(items, start=1):
                    matdoc.append([MANDT, str(doc_counter), year, f"{line:04d}", "101", item[5], plant[0], "0001",
                                   item[9], item[10], item[13], CURRENCY[plant[4]], d8(day), d8(day),
                                   rng.choice(USERS[:5]), po, item[2], "", "C", ts])
            for so, plant, items in rng.sample(open_sos, min(len(open_sos), rng.randint(3, 8))):
                doc_counter += 1
                for line, item in enumerate(items, start=1):
                    matdoc.append([MANDT, str(doc_counter), year, f"{line:04d}", "601", item[3], plant[0], "0001",
                                   item[5], "EA", item[7], CURRENCY[plant[4]], d8(day), d8(day), "BATCH_SD",
                                   "", "", so, "C", ts])
        write("MATDOC", day, ["MANDT", "MBLNR", "MJAHR", "ZEILE", "BWART", "MATNR", "WERKS", "LGORT", "MENGE",
                              "MEINS", "DMBTR", "WAERS", "BUDAT", "CPUDT", "USNAM", "EBELN", "EBELP", "KDAUF",
                              "ODQ_CHANGEMODE", "_EXTRACT_TS"], matdoc)

    files = sorted(OUT.rglob("*.csv"))
    rows = sum(sum(1 for _ in open(f, encoding="utf-8")) - 1 for f in files)
    print(f"Wrote {len(files)} files, {rows} data rows under {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
