# CarleCool: 0 € TikTok + Instagram mit Zernio (18.11.2026)

## Warum Zernio?
Offiziell **2 verbundene Social-Media-Accounts kostenlos**, Posts unbegrenzt,
API verfügbar, für die ersten 2 Accounts keine Kreditkarte notwendig.
CarleCool benötigt genau 1 Instagram + 1 TikTok.
Verbindliche Konditionen: https://docs.zernio.com/pricing und
https://docs.zernio.com/pricing/social

Zernio ist ein externer Dienst. Die Lizenz- und Musikrechte müssen vor
Veröffentlichung geklärt sein. Für Videos wird vorübergehend eine öffentliche
HTTPS-Medienadresse auf Zernios Infrastruktur erzeugt; das Video wird **nicht**
als öffentliches GitHub-Artefakt gespeichert.

## Einmalige Einrichtung, ohne eigene TikTok-App und ohne eigene Website

1. Bei https://zernio.com/ kostenlos registrieren.
2. Im Dashboard **ein Profil** für die Marke `CarleCool` erstellen.
3. **Ein Instagram-Konto** verbinden. Für automatisches Veröffentlichen ideal:
   Instagram Professional (Creator/Business).
4. **Ein TikTok-Konto** verbinden. Der neue TikTok-Connect-Weg bei Zernio
   verwendet die **TikTok for Business**-Anwendung des Dienstes. TikTok-
   Video-Direct-Posts sind darüber nur **öffentlich**. Bestätige bewusst
   TikToks Zugriffsanfrage und achte darauf, dass dies dein CarleCool-Account
   ist. Kein eigenes TikTok-Developer-App-Review nötig.
5. Öffne https://zernio.com/dashboard/api-keys und erstelle **einen API-Key**.
   Den geheimen Key niemals in Chat, Issue, E-Mail oder Repository-Datei posten.
6. Die verbundenen Account-IDs ermitteln: unter Zernio Accounts nachsehen
   oder per authentifiziertem `GET https://zernio.com/api/v1/accounts`;
   die IDs sind die `_id`-Felder jeweils für `platform: instagram`
   und `platform: tiktok`. Nicht den TikTok-/Instagram-Benutzernamen
   oder eine Social-Media-User-ID verwenden.
7. In GitHub: https://github.com/pcctradinginc-alt/carlecool-reels-automation/settings/secrets/actions
   → **New repository secret**, drei Secrets anlegen:
   - `ZERNIO_API_KEY`: Zernio-API-Key
   - `ZERNIO_INSTAGRAM_ACCOUNT_ID`: `_id` des verbundenen Instagram-Kontos
   - `ZERNIO_TIKTOK_ACCOUNT_ID`: `_id` des verbundenen TikTok-Kontos
8. **Gefahrloser Verbindungstest**: GitHub → Actions →
   **CarleCool — Zernio connection preflight (read-only)** → Run workflow.
   Dieser Workflow liest ausschließlich die Kontoverbindungen.
   Er lädt kein Medium hoch, veröffentlicht nichts und benötigt keinen
   aktivierten Publishing-Gate.
9. Erst nach bestandener Verbindung, nach Prüfung der Musik-, Stock- und
   KI-Videorechte und nach einem bewussten Entschluss zum Live-Posting
   diese **beiden getrennten** GitHub Secrets setzen:
   - `ZERNIO_PUBLISH_ENABLED` = `true` (aktiviert Zernio als Publisher)
   - `PUBLISH_ENABLED` = `true` (bestehende globale Sperre)
   `COVERR_PUBLISH_PERMISSION_CONFIRMED` nur bei tatsächlich bestätigten
   Coverr-Veröffentlichungsrechten aktivieren;
   `AI_VIDEO_PUBLISH_LICENSE_CONFIRMED` nur bei tatsächlich geprüfter
   KI-Modell-/Nutzungslizenz aktivieren. Keine Sperre automatisch umgehen.
10. Neue tägliche E-Mails enthalten weiterhin das MP4 und drei Möglichkeiten,
    die auf ein GitHub Review Issue führen. Nach Sichtung des Videos
    als GitHub-Eigentümer **genau einen** Befehl kommentieren:
    - `/publish instagram`: nur Instagram
    - `/publish tiktok`: nur TikTok (öffentlich)
    - `/publish both`: beide Plattformen (öffentlich auf TikTok)
    `/reject` verwirft, `/revise mehr natur, weniger skate` arbeitet um.

## Sicherheitskonzept
- Ein Mail-Link allein veröffentlicht nichts; nur Eigentümerkommentar.
- Das Original wird aus dem Gmail-Sent-Anhang mit SHA-256 verifiziert,
  danach über die signierte Zernio-Medienupload-URL übertragen.
- API-Post an beide Plattformen ist **eine Anfrage**. Bei gemischtem
  Erfolg (`207` oder Status `partial`) wird jede Plattform separat
  protokolliert. **Kein automatischer erneuter Upload:** Zernio-Dashboard
  und GitHub-`data/state.json` manuell abgleichen.
- GitHub legt vor externem Upload ein dauerhaftes Pending-Journal an.
  Bei API-Timeout oder unbekanntem Status kein blinder zweiter Versuch.
- Die letzte erfolgreiche Instagram-Integration bleibt unberührt,
  solange `ZERNIO_PUBLISH_ENABLED` nicht aktiviert wurde.
- Der neue Algorithmus für die letzten 20 SoundCloud-Songs, faire
  Zufallsrotation und die tägliche Review-Mail bleiben erhalten.

## Grenzen und Fragen vor Freigabe
- 0 € gilt für **genau 2 verbundene Accounts**. Ein dritter kann kostenpflichtig
  sein; keine Zusatzdienste wie SMS/Ads aktivieren.
- TikTok-API und Zernio haben eigene Sicherheits-/Tageslimits.
- Plattformen können Posts ablehnen. Die initiale API-Antwort muss
  tatsächlichen Erfolg für jede angeforderte Plattform bestätigen.
- TikTok Business API veröffentlicht Direktvideos öffentlich.
- Kein echtes Posting, OAuth oder Medienupload kann ohne deine
  verbundenen Konten und deine ausdrücklich aktivierten Gates
  als erfolgreich bestätigt werden.

Offizielle technische Quellen:
- https://docs.zernio.com/quickstart
- https://docs.zernio.com/platforms/tiktok
- https://docs.zernio.com/platforms/instagram
- https://docs.zernio.com/guides/media-uploads
- https://docs.zernio.com/guides/error-handling
