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

## 0. Where the code lives

Everything is on `origin/main` as of 2026-08-21. `git clone` gives you the current state — the
whole of the fold-8 work, the witness-map fix and this document included.

```
origin/main   3b003ed   Write SETUP.md: pulling, porting and mirroring the library
```

*Historical note, in case you meet an older checkout:* this work sat on a local-only branch
`slavonic-closeout` for a day, with no upstream, while `origin/main` was still at `17a6e8a`
("Calibrate the Slavonic…"). During that window a clone gave you the state from **before**
2026-08-20 — no fold 8, no witness fix, no guards — and looked entirely healthy while doing it.
The branch has since been fast-forwarded into `main` and pushed, so this no longer applies. If
you are ever unsure a checkout is current, the cheap check is:

```bash
git log --oneline -1            # compare against origin/main
git ls-remote --heads origin    # what actually exists upstream
```

**The general lesson is worth keeping even though the specific problem is gone:** a clone that
succeeds tells you nothing about whether the branch you wanted was ever pushed.

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
stock interpreter is fine.

**Install `python3-venv`.** An earlier draft of this file said it was unnecessary, "verified on
the source machine, which does not have that package". That verification was wrong, and the way
it was wrong is worth recording: `dpkg -l python3-venv` reports `un` — never installed — but
`ensurepip` comes from **`python3.14-venv`**, the versioned package, which *is* installed here:

```
$ dpkg -S /usr/lib/python3.14/ensurepip/__init__.py
python3.14-venv: /usr/lib/python3.14/ensurepip/__init__.py
```

So `python3 -m venv` succeeded on this box for a reason that will not hold on a minimal install,
where it fails with `ensurepip is not available`. Checking the meta-package name and concluding
nothing was needed is the same shape of error as everything else in this repository's history:
**a measurement that returned a confident answer to a question it was not actually asking.**

`lxml` installs from a `cp314` manylinux wheel, so **no compiler and no `libxml2-dev` are
needed**. The source machine has neither `python3-dev`, `libxslt1-dev` nor `sqlite3` installed
and the whole suite passes.

```bash
# on the NEW box
sudo apt update
sudo apt install -y git rsync curl python3-venv
```

`python3-venv` pulls in `python3.14-venv` and `python3-pip-whl`. Add `sqlite3` only if you want
the CLI for poking at the databases by hand.

`lxml` installs from a `cp314` manylinux wheel, so **no compiler and no `libxml2-dev` are
needed** — verified by building a clean venv from scratch: 32 packages, 46 MB of wheels, no
compiler invoked.

### SSH, so the copy can run unattended

```bash
# on the SOURCE machine — the new box will not accept a key until you put one there
ssh-copy-id marcoadmin@10.0.0.182
ssh marcoadmin@10.0.0.182 'echo ok'
```

---

## 3. Get the code

**Clone it — this is the normal path now:**

```bash
# on the NEW box
git clone https://github.com/msalazarm/biblereference.git ~/biblereference
cd ~/biblereference
git log --oneline -1
# expect: 3b003ed Write SETUP.md: pulling, porting and mirroring the library
```

**Alternative — copy it directly**, if the box has no internet or you have local commits that
are not upstream. Exclude the venv:

```bash
# on the SOURCE machine
rsync -avh --progress --exclude venv/ --exclude '__pycache__/' --exclude '.pytest_cache/' \
  ~/biblereference/ marcoadmin@10.0.0.182:~/biblereference/
```

`.git` comes with it, so the new box has the full history and can push later. Before doing this,
check you are not silently copying unpushed work — `git log --oneline origin/main..main` should
be empty.

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

**There is no lockfile, and nothing pins these.** The versions on the source machine as of
2026-08-21 are `pythonbible 0.15.5`, `lxml 6.1.1`, `jinja2 3.1.6`, `pyyaml 6.0.3`,
`platformdirs 4.11.0`, `httpx 0.28.1`, `regex 2026.7.19`, `beautifulsoup4 4.15.0`,
`pytest 9.1.1`, `ruff 0.16.1`, `mypy 2.3.0` — but a fresh install *today* already drifts from
them: lxml 6.1.2, mypy 2.3.1, ruff 0.16.4, platformdirs 4.11.3 and eight others. That list is a
**record of what was used, not a constraint**. If you need the two machines to agree exactly,
pin them yourself; nothing in the repository will do it for you.

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

**If you used `mirror`, everything below is already done.** `mirror` now runs the full
`rebuild` pipeline itself — that is the whole point of it being one command. It used to stop
after `build` + `index`, leaving the lemma lexicon, lemma index, parallel families, entity
index and profiles absent; if you are reading an older checkout, run `rebuild` by hand:

```bash
# on the NEW box, ONLY if you mirrored rather than copied corpus.sqlite
cd ~/biblereference
venv/bin/biblereference rebuild            # every derived layer, in order
```

`mirror` now runs this for you, so you should not need it — it is here for re-running a layer
by hand. Skipping it after a bare archive copy leaves `scan --inflected` finding nothing, with
no error.

**Route 2 — rebuild from the archive.** One command:

```bash
cd ~/biblereference
venv/bin/biblereference rebuild
```

It builds nine layers in dependency order:

```
verses → search index → lemma lexicon → lemma index → parallel families
       → entity index → verse profiles → scripture n-grams → ppmi vectors
```

No network. The CLTK lexicon zips, TIPNR, the four Theographic files and the OpenBible seed all
carry manifest lines, so a mirrored archive already holds them and `fetch_source` no-ops.

`biblereference rebuild --step NAME` runs one layer, repeatable. Its dependencies are still
checked against what is present **and non-empty**, so asking for a layer out of order refuses
rather than writing an empty one.

**An earlier version of this document listed those steps by hand and left out `parallels`.**
That was a real fault, not a typo: `build_profiles` reads `parallel_family` for its anchors, so
following the old list built the profiles against an empty families table — no error, no
warning, a profile set that looks built. The whole reason `rebuild` exists is that the order
and the dependencies are not something a person should have to keep in their head. A step whose
dependency did not build is now **skipped**, and a step that produces an empty layer is
reported **failed**, exit 1.

**Three states, and the difference matters.** A layer that builds reports its count. A layer
whose dependency did not build is **SKIPPED**. A layer that builds *nothing* is **FAILED** — an
empty table is not a built table — and the run exits 1. The last two layers are marked optional,
so they report **DEGRADED** instead: they run from `tools/`, which the wheel does not ship, and
PPMI additionally wants `sources/diorisis`, which no source registry publishes and `mirror`
therefore never copies. Neither should condemn a run that built everything else.

Two layers no rebuild can reach, because they are built from churchfathers' corpus:
`composite-grc.json` and `register-null-grc.json`. Copy them (Route 1) or go without —
`search`/`serve` simply take no `--composite`, and `register` scores against no null. The
command names them at the end rather than leaving a gap.

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
venv/bin/python -m pytest -q            # expect 1,149 passed
```

**What to expect depends on how much you have copied, and a green run early means less than it
looks.**

| state of the box | result |
|---|---|
| venv built, **no corpus yet** | **1,081 passed, 57 skipped** |
| corpus copied, no churchfathers | 1,148 passed, 1 skipped |
| everything, as on the source machine | **1,149 passed** |

The 57 skips are guarded on absent artifacts — *"needs a built library and `biblereference
lemmata`"*, *"ppmi artifact not built"*, *"&lt;corpus&gt; archive not fetched"*. **Nothing in that
run exercises the search index, the lemma index, PPMI, profiles or the calibration**, so a green
suite before you copy the data is close to meaningless. Run it again after §5.

The single remaining skip needs churchfathers' `ngrams-grc.sqlite3` at the current fold, and is
correct on a box that does not hold churchfathers.

### What `doctor` now catches, and what it still cannot

It reports a stale or unstamped fold for the **lemma lexicon**, the **entity index** and the
**parallel families**. All three fold their contents on the way in and none could say under
which rule until this week; between them they went several fold bumps unnoticed. An unstamped
one reports as *unknown*, never as current — "cannot say" reading as "fine" is precisely how
they hid.

**It cannot catch a true stamp on a stale input.** `profiles.sqlite` records its own fold
honestly, and for six fold bumps it recorded fold 8 while its anchors came from a
`parallel_family` table nobody had rebuilt. Reading a stamp back — the discipline below, which
caught every other fault this month — could not see it. Only rebuilding the layer underneath
and noticing the count move did. This is the argument for `rebuild` doing the whole chain
rather than you picking steps.

Then read a folded token **out** of an artifact rather than trusting its recorded
`fold_version` — this is how every one of the fold faults this month was found:

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

## 9. Quick reference

### The short way — mirror does the rest

If the source machine can serve, this is the whole port. `mirror` copies the archive
checksum-verified and then builds all nine layers itself.

```bash
# --- on the SOURCE machine ---
export BIBLEREFERENCE_TOKEN=$(openssl rand -hex 16); echo "$BIBLEREFERENCE_TOKEN"
venv/bin/biblereference serve --host 0.0.0.0 --port 8000 --token "$BIBLEREFERENCE_TOKEN"

# --- on the NEW box ---
sudo apt update && sudo apt install -y git curl python3-venv
git clone https://github.com/msalazarm/biblereference.git ~/biblereference
cd ~/biblereference
python3 -m venv venv && venv/bin/pip install --upgrade pip && venv/bin/pip install -e ".[dev,web]"
export BIBLEREFERENCE_TOKEN=<the token printed above>
venv/bin/biblereference mirror http://<source-host>:8000
venv/bin/biblereference doctor
```

637 MB over the wire and roughly 40 minutes of building. Afterwards, copy
`composite-grc.json` and `register-null-grc.json` if you want them — nothing can rebuild those
here. See §5b.

### The long way — copy the built artifacts instead

Assumes you clone the code (§3) and copy the artifacts (Route 1, §5b). Moves more bytes and
builds nothing.

```bash
# --- on the SOURCE machine ---
ssh-copy-id marcoadmin@10.0.0.182

rsync -avh --progress ~/.local/share/biblereference/sources/ \
  marcoadmin@10.0.0.182:~/.local/share/biblereference/sources/

D=~/.local/share/biblereference/db
rsync -avh --progress \
  $D/corpus.sqlite $D/entities.sqlite $D/profiles.sqlite \
  $D/ngrams-scripture-grc.sqlite3 $D/ppmi-grc.sqlite3 \
  $D/composite-grc.json $D/register-null-grc.json $D/control-fold6.json \
  marcoadmin@10.0.0.182:~/.local/share/biblereference/db/

# --- on the NEW box ---
sudo apt update && sudo apt install -y git rsync curl python3-venv
git clone https://github.com/msalazarm/biblereference.git ~/biblereference
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
