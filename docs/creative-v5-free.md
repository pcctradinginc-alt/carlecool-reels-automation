# CarleCool Creative v5 — kostenloser, isolierter Filmregisseur

## Status / Aktivierung
**Standard bleibt Creative v4.** Der tägliche 19:30-Workflow, die privaten
Genehmigungslinks, Gmail-Archiv, GitHub-Publishingjournal, Zernio und die
Instagram-/TikTok-Publisher bleiben unangetastet. `CARLECOOL_CREATIVE_V5`
steht ausschließlich im neuen, separaten Workflow auf `on`.

GitHub → Actions → **CarleCool — Creative v5 FREE private preview** →
**Run workflow**. Der Workflow erzeugt **nur** einen Testfilm und sendet ihn
privat per Gmail. Es wird **kein** Approval-Issue geöffnet. Kein Testvideo kann
durch das Anklicken eines Gmail-Links aus diesem Workflow veröffentlicht werden.
Der neue Workflow wird beim einmaligen Merge der Workflowdatei ebenfalls
einmal automatisch als privater Test ausgeführt.

Kein kostenpflichtiger Vision-Service, kein separater Video-KI-Service:
Das vorhandene öffentliche OpenCLIP-Modell wird auf einem Standard-CPU-Runner
geladen. Coverr und Pexels werden über **drei bestehende Suchlanes**
angesprochen: (1) erwachsene Frau, (2) Skater, (3) Cover-Motiv. Das steigert
die API-Anfragen pro Entwurf nicht über die bestehende Drei-Lane-Suche.
Coverr Demo und Pexels unterliegen weiterhin ihren Gratis-Limits;
bei Quota-Problemen gibt es **keine automatische kostenpflichtige Umstellung**.
Standardmäßig ruft der v5-Test keine optionale generative KI ab.

## Bildverständnis
Der originale SoundCloud-Cover wird **lokal** mit OpenCLIP gegen mehrere
gezielt ausgewählte Motiv-Prompts verglichen. Das sind Ähnlichkeitswerte,
**keine gesicherten Objektdetektionen und keine kalibrierten Wahrscheinlichkeiten**.
Bei unklarem Motiv entscheidet die bestehende Farbpalette.

- **Pferd/Reiter/Flagge** → nostalgische Americana, staubige Straße, warmer Filmlook.
- **Pastellfarbener Planet** → Pastellhimmel/ruhiger kosmischer Minimalismus.
- **Analoge Instrumente** → Studio, haptische Oberflächen.
- **Nächtliche Stadt** → reflektiertes Nachtlicht.
- **Küste/weißer Raum** → meditative Ruhe.

Gesteuert werden ausschließlich bereits lizenzierte, verfügbare Stockvideos,
keine Celebrity-Imitationen oder fremde Musikclips.

## Zwei verpflichtende Markensignaturen
Die Suchanfragen priorisieren **erwachsene weibliche Filmfigur** und
**Skateboarder**. Nach dem Download prüft OpenCLIP bis zu drei *tatsächliche
Frames pro Video* gegen positive und negative Bildbeschreibungen. Zwei
verschiedene Quelldateien müssen konservative Mindestwerte erreichen.
Ein einzelner Clip darf nicht beide Rollen erfüllen.

Falls keine ausreichend sicheren Clips gefunden werden, stoppt der
**private v5-Test vor E-Mail und Veröffentlichung**; der unveränderte
tägliche v4-Workflow läuft weiter. Diese technische Prüfung ist **nicht
unfehlbar**: vor produktiver Aktivierung die Menschen in den Videos
zusätzlich selbst visuell prüfen. Attraktivität wird nicht durch ein Modell
als Personenmerkmal bewertet; Inszenierung, Styling, Licht und Komposition
bestimmen den ästhetischen Eindruck.

## Schnitt
Die obligatorischen Personenaufnahmen werden als zwei getrennte,
musik-/beat-synchrone Szenen im Innenbereich des Films reserviert.
Der stärkste Cover-Frame kann den Anfang und das Ende gestalten; die
Signaturen erscheinen dazwischen. Smart Crop, Farb-LUTs, Ton-Mastering und
alle stabilen Renderparameter bleiben bestehen. Die dokumentierten
Urheberhinweise in der Caption bleiben unverändert.

## Schutz und Qualität
- Neuer Workflow: `permissions: contents: read`, keine GH-Write-Token,
  kein Zernio-/IG-/TikTok-Secret und kein `issue_comment`-Trigger.
- Aus der privaten Vorschau entsteht **kein** öffentliches Video-Artefakt,
  Genehmigungs-Issue oder Commit in `data/preview-history.json`.
- Benötigt vorhandenes kostenloses `open_clip_torch`; bei Ausfall kein
  teurer Cloud-Fallback. Die normalen Workflows bleiben verfügbar.
- Vor Freischaltung als Produktivstandard: echte Cover-/Hochformat-Tests,
  Videovergleich gegen v4, Kontrolle aller Stock-Lizenzen inkl. API-Attribution,
  GitHub-Runner-Minuten bei privaten Repositories und manuelle Freigabe.
- GitHub-hosted Actions sind für öffentliche Repositories in den allgemeinen
  Standard-Runner-Kontingenten kostenfrei; bei privaten Repositories können
  Freiminuten und Kontolimits relevant werden. Auch externe Anbieter können
  ihre Gratisbedingungen ändern. **0 € ist deshalb eine Kostenrestriktion
  des Workflows, keine Garantie für jedes GitHub-Konto.**

## Rollback
Creative-v5-Test-Workflow nicht mehr ausführen bzw. deaktivieren.
Keine Änderungen an der bestehenden Tagesproduktion notwendig.
