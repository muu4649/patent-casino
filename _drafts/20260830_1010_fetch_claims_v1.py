# -*- coding: utf-8 -*-
"""Google Patents の個別ページから 発明の名称 / 請求項1-2 / 出願人 / 分類 を取得する。

レート制限(503)対策として
  - リクエスト間隔 1.5秒 + 指数バックオフ
  - 1件ごとに JSONL へ追記保存（再実行時は取得済みをスキップしてレジューム）
"""
import json
import os
import random
import re
import time
import urllib.error
import urllib.request

from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
IDS = os.path.join(HERE, "20260830_0950_ids_v1.json")
OUT = os.path.join(HERE, "20260830_1010_claims_v1.jsonl")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")

PER_THEME = 11          # テーマあたり取得件数（18テーマ×11 ≒ 198件）
SLEEP = 1.5
MAX_RETRY = 5


def get(url):
    """503 は指数バックオフで粘る。取れなければ None。"""
    for attempt in range(MAX_RETRY):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            wait = (2 ** attempt) * 3 + random.uniform(0, 2)
            print("    {} -> wait {:.1f}s".format(e.code, wait))
            time.sleep(wait)
        except Exception as e:
            wait = (2 ** attempt) * 3
            print("    {} -> wait {}s".format(e, wait))
            time.sleep(wait)
    return None


def text_of(node):
    """<br/> を改行に、それ以外は素のテキストへ。"""
    for br in node.find_all("br"):
        br.replace_with("\n")
    t = node.get_text()
    t = re.sub(r"[ \t　]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def parse(html):
    soup = BeautifulSoup(html, "lxml")

    # 発明の名称: 特許庁原文(日本語)を優先
    title = ""
    for m in soup.find_all("meta", attrs={"name": "DC.title"}):
        title = (m.get("content") or "").strip()
        break
    if not title:
        h1 = soup.find("h1", attrs={"id": "title"})
        title = h1.get_text().strip() if h1 else ""

    # 請求項: load-source="patent-office" かつ lang=JA の <ol class="claims"> を優先
    claims_ol = None
    for ol in soup.find_all("ol", class_="claims"):
        if ol.get("lang") == "JA" and ol.get("load-source") == "patent-office":
            claims_ol = ol
            break
    if claims_ol is None:
        for ol in soup.find_all("ol", class_="claims"):
            if ol.get("lang") == "JA":
                claims_ol = ol
                break
    claims = []
    if claims_ol is not None:
        for li in claims_ol.find_all("li", class_="claim", recursive=False):
            div = li.find("div", class_="claim")
            num = (div.get("num") if div else None) or str(len(claims) + 1)
            body = li.find("div", class_="claim-text")
            if body is None:
                continue
            claims.append({"num": num, "text": text_of(body)})

    def meta_list(name):
        vals = []
        for m in soup.find_all("meta", attrs={"name": name}):
            v = (m.get("content") or "").strip()
            if v and v not in vals:
                vals.append(v)
        return vals

    return {
        "title": title,
        "claims": claims[:2],           # 請求項1〜2のみ
        "n_claims_total": len(claims),
        "assignee": meta_list("DC.contributor"),
        "date": (meta_list("DC.date") or [""])[0],
        "description_head": "",
    }


def main():
    ids = json.load(open(IDS, encoding="utf-8"))
    done = set()
    if os.path.exists(OUT):
        for line in open(OUT, encoding="utf-8"):
            try:
                done.add(json.loads(line)["num"])
            except Exception:
                pass
    print("取得済み {} 件".format(len(done)))

    targets = []
    for theme, v in ids.items():
        for h in v["hits"][:PER_THEME]:
            if h["num"] not in done:
                targets.append((theme, h))
    print("これから {} 件取得".format(len(targets)))

    ok = ng = 0
    with open(OUT, "a", encoding="utf-8") as f:
        for i, (theme, h) in enumerate(targets, 1):
            num = h["num"]
            url = "https://patents.google.com/patent/{}/ja".format(num)
            html = get(url)
            if not html:
                print("[{:3d}/{}] {:14s} FAIL".format(i, len(targets), num))
                ng += 1
                continue
            try:
                rec = parse(html)
            except Exception as e:
                print("[{:3d}/{}] {:14s} PARSE ERR {}".format(i, len(targets), num, e))
                ng += 1
                continue
            rec["num"] = num
            rec["theme"] = theme
            rec["url"] = url
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            ok += 1
            c1 = len(rec["claims"][0]["text"]) if rec["claims"] else 0
            print("[{:3d}/{}] {:14s} {:6s} cl={} len1={:4d} {}".format(
                i, len(targets), num, theme, rec["n_claims_total"], c1, rec["title"][:28]))
            time.sleep(SLEEP)

    print("--- OK {} / NG {} -> {}".format(ok, ng, OUT))


if __name__ == "__main__":
    main()
