# CarleCool – direkte E-Mail-Freigabe ohne GitHub-Kommentar (kostenlos)

**Status:** Quellcode und Tests liegen auf main. **Die Direktlinks werden erst aktiv, wenn der Cloudflare Worker tatsächlich bereitgestellt wurde.** Bis dahin führen die vier Optionen weiterhin sicher zum GitHub-Issue. Keine Veröffentlichung per einfachem Linkaufruf.

## Ergebnis

Die tägliche Freigabe-Mail zeigt vier Links:

1. **Nur TikTok** → bestätigte Aktion \`/publish tiktok\`
2. **Nur Instagram** → bestätigte Aktion \`/publish instagram\`
3. **TikTok & Instagram** → bestätigte Aktion \`/publish both\`
4. **Nicht veröffentlichen – Entwurf löschen** → \`/reject\`

Ein Link öffnet lediglich eine Bestätigungsseite. Du markierst dort die bewusste Zustimmung und klickst **Jetzt Veröffentlichung freigeben** bzw. **Entwurf verwerfen**. Es ist kein GitHub-Kommentar erforderlich.

**Wichtig zum Löschen:** Das Verwerfen schließt die ausstehende GitHub-Freigabe und verhindert die Veröffentlichung. Es löscht **nicht** die private E-Mail und ihren MP4-Anhang aus deinem Gmail-Posteingang bzw. Gesendet-Ordner. Diese Kopien kannst du in Gmail selbst löschen; Cloudflare speichert das Video nicht.

## Cloudflare Workers Free + D1 einmalig einrichten

1. Registriere dich kostenlos auf https://dash.cloudflare.com/ und wähle Workers & Pages. Für eine normale private Freigabe mit wenigen Aufrufen reicht typischerweise Workers Free + D1 Free. Nutzungsgrenzen gelten.
2. Auf deinem Rechner Node.js installieren. Clone dein Repo und wechsle in das Verzeichnis \`approval-worker\`.
3. Melde dich bei Cloudflare an: \`npx wrangler login\`.
4. Erstelle die kleine D1-Datenbank: \`npx wrangler d1 create carlecool-approvals\`. Kopiere die ausgegebene \`database_id\`.
5. Kopiere \`wrangler.toml.example\` nach \`wrangler.toml\` und trage die tatsächliche \`database_id\` ein. **Nicht** den Platzhalter stehen lassen.
6. Datenbanktabellen erstellen: \`npx wrangler d1 execute carlecool-approvals --remote --file=schema.sql\`.
7. Erzeuge lokal einen langen zufälligen Schlüssel, z.B.
   \`python3 -c "import secrets; print(secrets.token_urlsafe(48))"\`.
   Speichere ihn sicher. Im Cloudflare Worker: \`npx wrangler secret put APPROVAL_LINK_SECRET\`, dort **genau denselben Schlüssel** einsetzen.
8. In GitHub unter https://github.com/settings/personal-access-tokens eine **Fine-grained Personal Access Token** erstellen, der dem **Repository-Eigentümer** gehört und nur auf \`pcctradinginc-alt/carlecool-reels-automation\` zugreifen darf. Berechtigung **Issues: Read and write** (Metadata automatisch lesbar), möglichst kurze Laufzeit. Der Eigentümer ist entscheidend, da der existierende GitHub Actions Workflow ausschließlich seine Kommentare akzeptiert. Wenn das Repository unter einer Organisation statt dem persönlichen Konto liegt, muss die Authentifizierung/Gate vor Live-Betrieb angepasst werden.
9. Token **nur als Cloudflare Secret** hinterlegen: \`npx wrangler secret put GITHUB_APPROVAL_TOKEN\`. Nicht in GitHub-Dateien, Chatinhalte oder E-Mails einfügen.
10. Deploy: \`npx wrangler deploy\`. Notiere die reale HTTPS-Worker-URL, z.B. \`https://carlecool-approval.<dein-subdomain>.workers.dev\`. Das ist ein **Beispiel**, keine bereits eingerichtete URL.
11. In GitHub → Repository → Settings → Secrets and variables → Actions:
    - **Repository secret** \`APPROVAL_LINK_SECRET\` = derselbe zufällige Schlüssel aus Schritt 7.
    - **Repository variable** \`APPROVAL_BASE_URL\` = echte HTTPS-Worker-URL **ohne abschließenden Schrägstrich**.
12. Nächsten täglichen Review-Mail-Lauf starten. Die vier unterschiedlichen Links werden dann automatisch mit maximal 48 Stunden Gültigkeit erzeugt. Sie sind an das Freigabe-Issue, die GitHub-Run-ID und den SHA-256-Hash des Videos gebunden. Keine Links oder Geheimnisse in Screenshots oder öffentlich teilen.
13. **Zuerst den „Nicht veröffentlichen – Entwurf löschen“-Link an einem Testentwurf prüfen.** Nur die Bestätigungsseite öffnen, nichts sollte passieren; beim expliziten zweiten Klick muss das entsprechende GitHub-Issue geschlossen werden und es darf kein TikTok-/Instagram-Post entstehen. Danach separate Veröffentlichungstests auf einem neuen Entwurf durchführen.

## Sicherheit

- GET-Anfragen verändern nichts, auch nicht beim automatischen Öffnen durch Mailscanner.
- POST erfordert den zweiten Klick und Bestätigungs-Checkbox sowie Same-Origin-Prüfung.
- HMAC-SHA256 schützt den Link vor Manipulation, Laufzeit 48 Stunden.
- Die D1-Tabelle verhindert per atomarem INSERT eine zweite Entscheidung für dieselbe Freigabe.
- Bei unklarer GitHub-API-Antwort wird **nicht** automatisch erneut gesendet; manuelle Prüfung ist notwendig.
- Die Links sind Besitznachweise: Jede Person, die die E-Mail samt Link erhält, könnte auf der Bestätigungsseite handeln. Schütze dein Postfach und leite die E-Mail nicht weiter. Es gibt *kein zusätzliches Login*.
- Bisherige Sicherheitsgates \`PUBLISH_ENABLED\`, \`ZERNIO_PUBLISH_ENABLED\`, \`COVERR_PUBLISH_PERMISSION_CONFIRMED\` und persönliche Videofreigabe bleiben in Kraft.
- Löschen/Verwerfen kann laufende oder bereits veröffentlichte Posts **nicht rückwirkend entfernen**; nur einen noch offenen, nicht veröffentlichten Entwurf.

## Hinweis zu früheren Mails

Bereits versendete E-Mails werden nicht nachträglich geändert. Nur nach Einrichtung erzeugte Review-Mails enthalten die vier direkt aufrufbaren Bestätigungslinks.

Quellen:
- https://developers.cloudflare.com/workers/
- https://developers.cloudflare.com/d1/worker-api/
- https://developers.cloudflare.com/d1/platform/limits/
