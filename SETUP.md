# SETUP — installing, pulling, porting and mirroring biblereference

Three different operations get confused with each other, so they are named separately here:

| verb | what it means | command |
|---|---|---|
| **pull** | fetch source texts from *upstream on the internet* into the archive | `biblereference sync` / `fetch` |
| **port** | stand the whole library up on a **new machine** | this document, §§2-6 |
| **mirror** | make a second machine hold **byte-identical** archive to this one | `biblereference mirror` (§5a) |

`sync` and `mirror` are not interchangeable, and the CLI says why:

> *Use this rather than `sync` when two machines must match: `sync` takes whatever upstream
> publishes today, and upstream changes.*

So: **pull** to get new material, **mirror** to make two machines agree. If you want the new box
to match this one, never use `sync` on it.

Worked example target: `marcoadmin@10.0.0.182`, clean Ubuntu install. Scope is
**biblereference only** — churchfathers is not covered here.

Measured on the source machine 2026-08-21. Every size and version below was read off the
system, not estimated.

---

## 0. Read this first — a `git clone` will NOT give you the current state

```
biblereference branch  slavonic-closeout
  exists on GitHub?    NO  (git ls-remote --heads origin slavonic-closeout -> 0 matches)
  upstream configured? NO
  commits not on origin/main:  42
  origin/main is at    17a6e8a   ("Calibrate the Slavonic…")
  local HEAD is at     3abb1a1   ("Read Judith 16 whole…")
```

**Cloning from GitHub lands you on `17a6e8a`, which is the state from before 2026-08-20.**
That means no fold 8, no witness-map fix, none of the guards, neither handoff document.

Pick one before you do anything else:

**Option A — push first (recommended; it is also a backup)**

```bash
# on the SOURCE machine
cd ~/biblereference
git push -u origin slavonic-closeout
```

Then the new box can clone normally. Do this only if you are happy for the branch to be on
GitHub — it is currently local-only, which may be deliberate.

**Option B — copy the repo directly, `.git` included**

Covered in §3 below. Nothing is published; the new box gets a full clone-equivalent.

---

## 1. What actually has to move

| what | size | notes |
|---|---|---|
| repo **without** `venv/` | **32 MB** | `.git` is 16 MB of that |
| `~/.local/share/biblereference/sources/` | **637 MB** | 76 sources, 639-entry MANIFEST with checksums |
| `db/` — **live artifacts only** | **1,529 MB** | see §5; the rest of `db/` is backups |
| `audit/` | 78 MB | judgement databases; only if you want the history |
| **total** | **≈ 2.3 GB** | against 4.8 GB if you copy blindly |

**Do not copy `venv/` (363 MB).** It hard-codes `/home/marcollm/...` paths in `pyvenv.cfg` and
every console script. Rebuild it on the target — it takes under a minute.

`db/` holds **2,186 MB of dead weight**: `corpus-from-remote-2026-08-14.sqlite` (745 MB),
`corpus-before-portion-drop.sqlite` (580 MB), `ngrams-…fold2` (199 MB), two stale `ppmi` backups
(196 MB each), and five superseded `control-*.json`. None of it is needed.

---

## 2. System prep on the new box

Ubuntu 26.04 ships Python **3.14.4** as `python3`, and the package requires `>=3.11`, so the
stock interpreter is fine. **`python3 -m venv` works without `python3-venv` installed** — verified
on the source machine, which does not have that package.

`lxml` installs from a `cp314` manylinux wheel, so **no compiler and no `libxml2-dev` are
needed**. The source machine has neither `python3-dev`, `libxslt1-dev` nor `sqlite3` installed
and the whole suite passes.

```bash
# on the NEW box
sudo apt update
sudo apt install -y git rsync curl
```

That is genuinely the whole list. Add `sqlite3` only if you want the CLI for poking at the
databases by hand.

### SSH, so the copy can run unattended

```bash
# on the SOURCE machine — the new box will not accept a key until you put one there
ssh-copy-id marcoadmin@10.0.0.182
ssh marcoadmin@10.0.0.182 'echo ok'
```

---

## 3. Get the code

**If you pushed (Option A):**

```bash
# on the NEW box
git clone https://github.com/msalazarm/biblereference.git ~/biblereference
cd ~/biblereference
git checkout slavonic-closeout
```

**If you did not (Option B) — copy it, excluding the venv:**

```bash
# on the SOURCE machine
rsync -avh --progress --exclude venv/ --exclude '__pycache__/' --exclude '.pytest_cache/' \
  ~/biblereference/ marcoadmin@10.0.0.182:~/biblereference/
```

`.git` comes with it, so the new box has the full history and can push later.

Confirm on the new box:

```bash
cd ~/biblereference && git log --oneline -1
# expect: 3abb1a1 Read Judith 16 whole, and stop one decision short of writing it
```

---

## 4. Build the environment

```bash
# on the NEW box
cd ~/biblereference
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -e ".[dev,web]"
venv/bin/biblereference --help
```

Pinned versions currently in use, if you need to match exactly: `pythonbible 0.15.5`,
`lxml 6.1.1`, `jinja2 3.1.6`, `pyyaml 6.0.3`, `platformdirs 4.11.0`, `httpx 0.28.1`,
`regex 2026.7.19`, `beautifulsoup4 4.15.0`, `pytest 9.1.1`, `ruff 0.16.1`, `mypy 2.3.0`.

---

## 5. Move the data

The data home defaults to `~/.local/share/biblereference` and is overridden by
**`$BIBLEREFERENCE_HOME`**. If you want it elsewhere on the new box, export that first and use
it consistently.

### 5a. The archive — use `mirror`, not rsync

The project has a purpose-built command for this, and it checksum-verifies every file against
what the source machine recorded:

> *Points this machine at another one running `biblereference serve` and copies its archive,
> verifying every file against the checksum that machine recorded before writing it. Then
> rebuilds. Use this rather than `sync` when two machines must match: `sync` takes whatever
> upstream publishes today, and upstream changes.*

```bash
# on the SOURCE machine — serve the archive on the LAN behind a token
export BIBLEREFERENCE_TOKEN=$(openssl rand -hex 16); echo "token: $BIBLEREFERENCE_TOKEN"
venv/bin/biblereference serve --host 0.0.0.0 --port 8000 --token "$BIBLEREFERENCE_TOKEN"
```

```bash
# on the NEW box, with the same token
cd ~/biblereference
export BIBLEREFERENCE_TOKEN=<the token printed above>
venv/bin/biblereference mirror http://10.0.0.<source>:8000
```

`mirror` copies the archive, refuses any file whose checksum does not match, then runs `build`
and `index` for you. **Prefer this over rsync for `sources/`** — you get verification free.

Plain rsync, if you would rather not run a server:

```bash
rsync -avh --progress ~/.local/share/biblereference/sources/ \
  marcoadmin@10.0.0.182:~/.local/share/biblereference/sources/
```

...then on the new box: `venv/bin/biblereference build && venv/bin/biblereference index`.

### 5b. The derived artifacts — copy or rebuild

`mirror` gives you `corpus.sqlite` and the search index. It does **not** build the lemma index,
n-grams, PPMI, profiles or the calibration. You have two routes.

**Route 1 — copy them (≈ 20 minutes on a LAN).** The live set only:

```bash
# on the SOURCE machine
D=~/.local/share/biblereference/db
rsync -avh --progress \
  $D/entities.sqlite $D/profiles.sqlite $D/ngrams-scripture-grc.sqlite3 \
  $D/ppmi-grc.sqlite3 $D/composite-grc.json $D/register-null-grc.json \
  $D/control-fold6.json \
  marcoadmin@10.0.0.182:~/.local/share/biblereference/db/
```

**If you also rsync'd `corpus.sqlite` (rather than using `mirror`), you are done — nothing needs
rebuilding.** `corpus.sqlite` holds 27 tables and carries all of it: the verse store
(`verse`, `source_meta`, `chapter_state`), the **search index** (`search_state`, `search_fts`,
`search_text`, `search_df`), the **lemma index** (`lemma_state`, `lemma_fts`, `lemma_text`,
`lemma_df`) **and the lemma lexicon** (`lemma_form`, `lemma_form_state`).

**If you used `mirror`, you must still build the lemma side.** `mirror` rebuilds
`corpus.sqlite` from the archive and its rebuild is `build` + `index` only — it does not fetch
the lexicon or build the lemma index:

```bash
# on the NEW box, ONLY if you mirrored rather than copied corpus.sqlite
cd ~/biblereference
venv/bin/biblereference lemmata            # ~6 min, 33 MB download
venv/bin/biblereference index --lemmata    # ~4 min
```

Skipping this after a `mirror` leaves `scan --inflected` finding nothing, with no error.

**Route 2 — rebuild from the archive (≈ 4.5 hours, most of it one job).** Measured on the
source machine 2026-08-21:

```bash
cd ~/biblereference
D=~/.local/share/biblereference/db
venv/bin/biblereference lemmata                                   # ~6 min (33 MB download)
venv/bin/biblereference index --lemmata                           # ~4 min
venv/bin/biblereference entities                                  # entity index
venv/bin/python tools/scripture_ngrams.py --language grc          # ~4 min
venv/bin/python tools/ppmi_vectors.py --save $D/ppmi-grc.sqlite3  # ~4 min
venv/bin/python -m biblereference.profiles                        # ~12 min
venv/bin/python tools/calibrate_inflected.py --control 3000000 \
  --save $D/control.json --workers 10                             # ~3 HOURS, 22,372 shards
venv/bin/python tools/fs_composite.py --sample 1200 \
  --control-evidence $D/control.json --weights $D/composite-grc.json  # ~1 min
```

**`register-null-grc.json` cannot be rebuilt here** — it is built from churchfathers'
`ngrams-grc.sqlite3`, which is out of scope for this box. Copy it (Route 1) or leave it absent.

Copying is the better trade unless you specifically want to re-derive the calibration: the
control-evidence job is three hours and produces the same answer.

### 5c. Optional — the judgement history

```bash
rsync -avh --progress ~/.local/share/biblereference/audit/ \
  marcoadmin@10.0.0.182:~/.local/share/biblereference/audit/     # 78 MB
```

Only needed if you want the cross-language adjudication results. Nothing in the library reads it.

---

## 6. Verify — and do not trust the stamps

```bash
cd ~/biblereference
venv/bin/biblereference doctor          # should report no drift and no stale folds
venv/bin/python -m pytest -q            # expect 1,137 passed, 1 skipped
```

The skip is a known one: it needs a consumer artifact this box does not have.

Then read a folded token **out** of an artifact rather than trusting its recorded
`fold_version` — this is how every one of the six fold faults this month was found:

```bash
venv/bin/python - <<'PY'
import sqlite3, pathlib
from biblereference.emphasis import FOLD_VERSION
D = pathlib.Path.home() / ".local/share/biblereference/db"
ng = sqlite3.connect(f"file:{D/'ngrams-scripture-grc.sqlite3'}?mode=ro", uri=True)
g = lambda w: ng.execute(
    'SELECT SUM(count) FROM ngram WHERE fold=? AND "order"=1 AND author<>?', (w, "")
).fetchone()[0] or 0
print("fold", FOLD_VERSION, "| expect 8")
print("εσται      ", f"{g('εσται'):,}", "expect 3,771  (0 means a pre-fold-7 artifact)")
print("εσταυρωται ", g("εσταυρωται"), "expect 4      (thousands means the ἔσται bug)")
print("ουτωσ      ", g("ουτωσ"), "expect 0")
print("πρω        ", g("πρω"), "expect 0")
PY
```

A search that returns its own verse at similarity 1.000 is the end-to-end check:

```bash
venv/bin/biblereference search "Ἐν ἀρχῇ ἦν ὁ Λόγος, καὶ ὁ Λόγος ἦν πρὸς τὸν Θεόν"
```

---

## 7. Not covered here

* **Model servers.** `tools/overnight.py` and the adjudication tooling talk to llama.cpp servers
  on `:8080` (gemma-4-26B) and `:8081` (gemma-4-E4B). Nothing in the library proper needs them —
  only the lab tooling. Setting them up is a separate job: NVIDIA driver, llama.cpp, and the
  `.gguf` weights, none of which live in this repo.
* **churchfathers**, and therefore `register-null-grc.json`'s rebuild path.
* **Licensing.** `src/biblereference/data/NOTICE.md` and `COPENHAGEN-LICENSE.md` cover the
  versification data; the source archive's MANIFEST records a licence per file. Copying between
  two machines you own is fine; redistributing is not automatically so.


---

## 8. Keeping two machines in step afterwards

Once both boxes are up, this is the routine — and the order matters.

### Pulling new source texts (either machine)

```bash
venv/bin/biblereference sync              # fetch + build + index everything new
venv/bin/biblereference sync --source X   # just one
venv/bin/biblereference sync --force      # re-fetch even if already archived
```

`sync` writes only to `sources/`, then rebuilds from it. It takes whatever upstream publishes
**today**, so two machines that both `sync` on different days can end up holding different
bytes. That is the whole reason `mirror` exists.

### Making the second machine match (the safe routine)

```bash
# 1. on the machine that has the material you want to be canonical
export BIBLEREFERENCE_TOKEN=$(openssl rand -hex 16); echo "$BIBLEREFERENCE_TOKEN"
venv/bin/biblereference serve --host 0.0.0.0 --port 8000 --token "$BIBLEREFERENCE_TOKEN"

# 2. on the other machine
export BIBLEREFERENCE_TOKEN=<same token>
venv/bin/biblereference mirror http://<canonical-host>:8000
```

Every file is checked against the checksum the serving machine recorded **before** it is
written. If any file fails, `mirror` refuses the whole batch and builds nothing:

```
N file(s) refused; nothing was built. Try again.
```

That is the behaviour you want — a partial archive that looks complete is the failure mode this
guards against. Use `--no-build` if you want the bytes now and the rebuild later.

### Which machine should be canonical

Whichever one last ran `sync`. `mirror` is one-directional: it makes the *calling* machine match
the *served* one. There is no merge, so decide the direction before you start.

### After any archive change, on both machines

```bash
venv/bin/biblereference doctor
```

It reports stale folds and a drifted index, which is what you will actually get wrong. The
derived artifacts (§5b) do **not** rebuild themselves — `doctor` naming them is your reminder.

---

## 9. Quick reference — the whole port in one block

Assumes you chose Option B (copy the repo) and Route 1 (copy the artifacts).

```bash
# --- on the SOURCE machine ---
ssh-copy-id marcoadmin@10.0.0.182

rsync -avh --progress --exclude venv/ --exclude '__pycache__/' --exclude '.pytest_cache/' \
  ~/biblereference/ marcoadmin@10.0.0.182:~/biblereference/

rsync -avh --progress ~/.local/share/biblereference/sources/ \
  marcoadmin@10.0.0.182:~/.local/share/biblereference/sources/

D=~/.local/share/biblereference/db
rsync -avh --progress \
  $D/corpus.sqlite $D/entities.sqlite $D/profiles.sqlite \
  $D/ngrams-scripture-grc.sqlite3 $D/ppmi-grc.sqlite3 \
  $D/composite-grc.json $D/register-null-grc.json $D/control-fold6.json \
  marcoadmin@10.0.0.182:~/.local/share/biblereference/db/

# --- on the NEW box ---
sudo apt update && sudo apt install -y git rsync curl
cd ~/biblereference
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -e ".[dev,web]"
venv/bin/biblereference doctor
venv/bin/python -m pytest -q
```

≈ 2.3 GB over the wire, and **no rebuild step at all** — the copied `corpus.sqlite` already
carries the verse store, both indexes and the lexicon. (Had you mirrored instead of copying it,
you would need `lemmata` and `index --lemmata` here; see §5b.)
