<p align="center">
  <img src="docs/brand/samadcon-3a-transparent.svg"
       alt="SAMADCON — the Samba AD console" width="560">
</p>

<p align="center"><em><a href="README.md">English version</a></em></p>

Browserbasierte Verwaltungskonsole für Samba-AD-DC-Domänen. Ersetzt die Windows-RSAT-Werkzeuge
(ADUC, DNS-Manager, Sites & Services, GPMC) durch einen Docker-Container — **inklusive
Gruppenrichtlinien-Editor**, den vergleichbare Projekte auslassen.

SAMADCON spricht ausschließlich Standardprotokolle: **LDAPS, Kerberos und SMB**. Der Container
muss nicht auf einem Domänencontroller laufen und greift nie direkt auf dessen Dateisystem zu.

> Status: in Entwicklung. Der Umsetzungsstand steht unter [Meilensteine](#meilensteine).

## Warum

RSAT setzt einen domänengejointen Windows-Client voraus. In reinen Linux-Umgebungen fällt es damit
komplett aus, und `samba-tool` deckt als CLI-Werkzeug nur einen Teil des Tagesgeschäfts ab.

## Sicherheitsmodell

Jeder Administrator meldet sich mit seinem **eigenen AD-Konto** an. SAMADCON holt pro Sitzung ein
Kerberos-TGT in einen sitzungseigenen Credential-Cache auf tmpfs und führt **alle** LDAP- und
SMB-Operationen mit den Rechten dieses Kontos aus:

- Das Tool selbst braucht **kein** privilegiertes Dienstkonto.
- AD-Delegation, Sicherheitsfilterung und serverseitiges Auditing bleiben wirksam.
- Das Passwort wird nur zur Ticket-Beschaffung verwendet, **nie gespeichert und nie geloggt**.
- Jede schreibende Operation landet zusätzlich im lokalen Audit-Log (wer, was, DN, Attribut-Diff).

## Mehrere Domänen

Die Domäne wird **bei der Anmeldung** gewählt, nicht beim Start des Containers. In der
Anmeldemaske stehen zur Auswahl:

- **Freie Eingabe** einer IP-Adresse oder eines Hostnamens,
- **vorkonfigurierte Domänen** aus `SAMADCON_SERVERS_FILE` (siehe
  [servers.example.json](docker/servers/servers.example.json)),
- **zuletzt verwendete** Server (nur im Browser gespeichert, keine Zugangsdaten),
- die im Container hinterlegte **Standarddomäne**, falls konfiguriert.

Bei Eingabe einer IP ermittelt SAMADCON die Domäne selbst: Ein anonymer rootDSE-Abruf liefert
Realm, den FQDN des Domänencontrollers und die Naming Contexts. Das ist nötig, weil Kerberos
Tickets auf `ldap/dc1.example.lan@EXAMPLE.LAN` ausstellt — aus einer nackten IP lässt sich weder
der SPN noch der Realm ableiten. Anschließend wird eine Kerberos-Konfiguration erzeugt, die genau
diese Adresse als KDC einträgt; damit funktioniert die Anmeldung auch ohne passende DNS-Einträge.
Mehrere Realms werden parallel unterstützt.

### Transport

SAMADCON verbindet sich in zwei Stufen, beide verschlüsselt:

1. **LDAP (389) mit GSSAPI Sign&Seal** — der Kerberos-Sitzungsschlüssel verschlüsselt den Verkehr,
   ganz ohne Zertifikat. Das ist der Weg, den `samba-tool` und die Windows-Werkzeuge gehen, und der
   in Sambas Client-Stack am besten unterstützte.
2. **LDAPS (636)** als Rückfallebene, falls Port 389 gesperrt ist.

`seal` wird dabei *verlangt*, nicht erbeten: Ein Server, der es nicht kann, lässt die Verbindung
scheitern, statt still auf Klartext herunterzustufen.

Die Anmeldemaske meldet vorab, ob das LDAPS-Zertifikat überprüfbar ist. Bei einem selbstsignierten
Samba-Zertifikat kann die Prüfung **pro Sitzung** abgeschaltet werden — das betrifft aber nur
Stufe 2. Für den Normalfall ist weder ein Zertifikat noch eine CA-Datei nötig.

## Schnellstart

### Das fertige Image verwenden

Jeder Push auf den Standardbranch baut ein Image und legt es in der GitHub Container Registry ab.
Es muss nichts geklont und nichts gebaut werden:

```bash
docker pull ghcr.io/onlinecrash24/samadcon:latest
```

Eine `docker-compose.yml` für dieses Image, vollständig so wie sie dasteht — in ein leeres
Verzeichnis legen:

```yaml
services:
  samadcon:
    image: ghcr.io/onlinecrash24/samadcon:latest
    container_name: samadcon
    restart: unless-stopped

    environment:
      # Der Name, unter dem die Konsole erreichbar ist. Er landet als CN und SAN
      # im selbstsignierten Zertifikat und als Ziel der HTTPS-Weiterleitung —
      # der einzige Wert, den praktisch jede Installation ändern muss.
      SAMADCON_PUBLIC_HOST: "samadcon.example.lan"
      # Muss den Port nennen, den der Host veröffentlicht, nicht den von nginx.
      SAMADCON_PUBLIC_HTTPS_PORT: "8443"

      # Beide dürfen leer bleiben: dann fragt die Anmeldemaske nach einer
      # Serveradresse. Wenn gesetzt, dann auflösbare Namen — Kerberos braucht
      # den FQDN des DCs, eine nackte IP scheitert mit
      # NT_STATUS_INVALID_PARAMETER.
      SAMADCON_REALM: ""
      SAMADCON_DC_HOSTS: ""

      SAMADCON_LOG_LEVEL: "INFO"

    ports:
      - "8443:8443"
      - "8080:8080"

    volumes:
      # Ein echtes Zertifikat kommt hier als server.crt und server.key hinein.
      # Ohne eines erzeugt der Container beim ersten Start ein selbstsigniertes.
      - ./tls:/etc/samadcon/tls
      # CA-Bündel zur Prüfung der LDAPS-Zertifikate der DCs.
      - ./ca:/etc/samadcon/ca:ro
      - samadcon-cache:/var/cache/samadcon
      - samadcon-data:/var/lib/samadcon
      # Der Audit-Verlauf soll den Container überleben.
      - samadcon-logs:/var/log/samadcon

    # Kerberos-Credential-Caches liegen in /dev/shm und dürfen nie auf Platte.
    shm_size: 64m
    tmpfs:
      # uid/gid sind nötig: ein tmpfs-Mount gehört per Vorgabe root, und nginx
      # und supervisor laufen als uid 1000.
      - /run/samadcon:mode=0700,uid=1000,gid=1000,size=8m

    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL

volumes:
  samadcon-cache:
  samadcon-data:
  samadcon-logs:
```

Der Container läuft als uid 1000, ein Bind-Mount gehört root — das Zertifikatsverzeichnis muss
also für ihn beschreibbar sein. Sonst weicht der Entrypoint mit einer Warnung in ein Volume aus,
und das Zertifikat liegt nicht dort, wo man es sucht:

```bash
mkdir -p tls ca && sudo chown -R 1000:1000 tls
docker compose up -d
```

**Welcher Tag.** `latest` folgt dem Standardbranch, `DEV` benennt ihn ausdrücklich, und jeder Bau
trägt zusätzlich `sha-<kurz>`. Für alles, woran etwas hängt, den `sha-`Tag festnageln: `latest`
wandert beim nächsten Push unter Ihnen weg.

### Aus dem Quelltext bauen

```bash
git clone https://github.com/onlinecrash24/SAMADCON.git
cd SAMADCON
docker compose up -d --build
```

Keine `.env` nötig — die gesamte Konfiguration steht in `docker-compose.yml`. Ohne eingetragene
Domäne fragt die Anmeldemaske nach einer Serveradresse und ermittelt den Rest selbst.

Die Oberfläche läuft anschließend auf `https://<host>:8443`. Ohne gemountetes Zertifikat erzeugt
der Container beim ersten Start ein selbstsigniertes.

## Deployment

### Was auf dem Zielsystem liegen muss

```
SAMADCON/
├── docker-compose.yml          die gesamte Konfiguration
├── .dockerignore               hält node_modules und lokale Geheimnisse aus dem Image
├── docker/
│   ├── Dockerfile
│   ├── entrypoint.sh
│   ├── nginx.conf.template
│   └── supervisord.conf
├── backend/
│   ├── pyproject.toml
│   └── samadcon/
└── frontend/
    ├── package.json
    ├── package-lock.json
    ├── index.html
    ├── tsconfig.json
    ├── vite.config.ts
    ├── src/
    └── public/
```

`backend/tests/` wird nur gebraucht, wenn mit `SAMADCON_TARGET=test` gebaut wird.

Nicht mitkopieren: `frontend/node_modules`, `frontend/dist`, `backend/samadcon.egg-info`, alle
`__pycache__`, `.venv`. Die `.dockerignore` fängt das ab und hält zugleich Zertifikate und eine
etwaige lokale `.env` aus dem Image — Konfiguration kommt zur Laufzeit, nie in eine Bildschicht.

`docker/tls/`, `docker/ca/` und `docker/servers/` entstehen beim ersten Start.

Nichts davon wird gebraucht, wenn Sie das fertige Image verwenden: es bringt alles mit.

### Was eingestellt werden muss

**Keine `.env`.** Alles steht in `docker-compose.yml`, mit dem Wert, den es haben soll — kein
zweiter Ort, der mitgepflegt werden will, und nichts, das stillschweigend auf einen Leerstring
zurückfällt, weil eine Variable nicht exportiert war.

| Einstellung | Wofür |
|---|---|
| `SAMADCON_PUBLIC_HOST` | Der Name, unter dem die Konsole erreichbar ist. Landet als CN und SAN im selbstsignierten Zertifikat und in der HTTPS-Weiterleitung. **Der einzige Wert, den praktisch jede Installation ändern muss.** |
| `SAMADCON_REALM`, `SAMADCON_DC_HOSTS` | Vorbelegung der Anmeldemaske. **Auflösbare Namen, keine nackten IP-Adressen** — Kerberos braucht den FQDN des DCs. |
| `SAMADCON_LDAP_CA_FILE` | Die CA des DCs, wenn das LDAPS-Zertifikat geprüft werden soll. |

Was zur Maschine gehört statt zum Projekt, bleibt als `${VAR:-Vorgabe}` stehen und kommt aus der
Shell: die Ports, falls 8443 oder 8080 belegt sind, `SAMADCON_TARGET=test` für das Testimage, und
die `TEST_*`-Werte der Integrationstests. **Ein Kennwort gehört nie in die Compose-Datei** — die
liegt in der Versionskontrolle.

### Ablauf

`docker-compose.yml` anpassen, mindestens `SAMADCON_PUBLIC_HOST`. Dann:

```bash
docker compose up -d --build
```

Für ein echtes Zertifikat `server.crt` und `server.key` nach `docker/tls/` legen. Eine Sache
dabei: der Container läuft als uid 1000, ein Bind-Mount vom Host gehört root. Ist `docker/tls/`
nicht beschreibbar, weicht der Entrypoint mit einer Warnung ins Volume `samadcon-data` aus — das
Zertifikat liegt dann nicht dort, wo man es sucht. Deshalb einmalig:

```bash
mkdir -p docker/tls docker/ca && chown -R 1000:1000 docker/tls
```

Prüfen:

```bash
docker compose ps
```

Der Container hat einen Healthcheck auf `/api/v1/health` und meldet sich nach etwa zwanzig
Sekunden als `healthy`. Wenn nicht, sagt `docker compose logs samadcon` warum. Die Verbindung zum
DC lässt sich ohne Zugangsdaten prüfen:

```bash
docker compose exec samadcon samadconctl probe dc1.example.lan
```

Aktualisieren ist derselbe Befehl wie das Aufsetzen. Die Volumes `samadcon-cache`, `samadcon-data`
und `samadcon-logs` — dort liegt der Audit-Verlauf — überleben das:

```bash
docker compose up -d --build
```

## Test gegen einen vorhandenen Samba AD

Die Zugangsdaten kommen aus der Shell, nicht aus einer Datei — ein Domänenadministrator-Kennwort
hat in keiner Datei etwas verloren, die versehentlich mitgesichert werden kann.

Die Tests liegen im Image, nicht im Mount — dafür braucht es das Build-Ziel `test`:

```bash
SAMADCON_TARGET=test docker compose up -d --build
```

Integrationstests gegen diese Domäne:

```bash
TEST_DC_HOST=dc1.example.lan TEST_ADMIN_PASSWORD=... docker compose exec samadcon python -m pytest tests/integration -q
```

> Ein geänderter Test wird beim Bauen ins Image kopiert. Nach jeder Änderung an den Tests also
> erst `up -d --build`, dann `exec`.

> Die Tests legen Objekte an und löschen sie wieder — jeweils in einer eigenen OU
> `samadcon-test-<zufall>`. Nur gegen eine Testdomäne laufen lassen.

Wenn die Verbindung nicht zustande kommt, beantwortet das CLI im Container die Frage, woran es
liegt — ohne Zugangsdaten:

```bash
docker compose exec samadcon samadconctl probe 192.168.1.10
```

Und mit Anmeldung, den ganzen Weg bis zum rootDSE:

```bash
docker compose exec samadcon samadconctl check --server 192.168.1.10 --insecure
```

## Meilensteine

| # | Umfang | Status |
|---|---|---|
| 1 | Fundament, Auth, Benutzer/Gruppen/Computer/OUs (ADUC-Ersatz) | steht, gegen eine echte Domäne verifiziert |
| 2 | DNS, Sites & Services, Diagnose (FSMO, Replikation, Passwortrichtlinien) | steht, gegen eine echte Domäne verifiziert |
| 3 | GPMC-Basis: GPOs, Verknüpfungen, Filterung, Backup/Restore, Report | steht, gegen eine echte Domäne verifiziert |
| 4 | GPO-Editor: ADMX → Sicherheitseinstellungen → Linux/VGP → Preferences → Skripte/Ordnerumleitung | vollständig; jeder der fünf Teilbereiche auf einem echten Client als **angewendet** nachgewiesen (4c über `samba-gpupdate --rsop`), Preferences in allen drei Wellen |

Meilenstein 1 umfasst: Kerberos-Sitzungen, Baumnavigation, Objektlisten und Suche (ANR),
Benutzer (anlegen, bearbeiten, Kontooptionen, Passwort-Reset, Entsperren, Ablauf),
Gruppen (Bereich/Typ, Mitglieder inkl. verschachtelt und primär), Computer (inkl. LAPS-Lesen und
Konto-Reset), OUs (inkl. Löschschutz), Verschieben/Umbenennen/Löschen, Attribut-Editor,
ACL- und Delegationseditor, Audit-Log und die deutsche/englische Oberfläche.

Der DNS-Teil aus Meilenstein 2 arbeitet über LDAP statt über die DCE/RPC-Schnittstelle
(`samba-tool dns`): Zonen aus allen drei Partitionen — Domäne, Forest und der alten Ablage
unter `CN=System` —, Einträge der Typen A, AAAA, CNAME, NS, PTR, MX, SRV und TXT anlegen,
ändern und löschen, dazu Zonen anlegen und löschen. Ein Name ist in AD **ein** Objekt mit
allen seinen Einträgen in einem mehrwertigen Attribut; SAMADCON zeigt trotzdem eine Zeile je
Eintrag und findet den zu ändernden über seine bisherigen Werte wieder. Passt der Eintrag
nicht mehr, hat ihn jemand anders geändert — dann bricht die Änderung ab, statt zu raten.
Jede Änderung zieht die SOA-Seriennummer der Zone hoch und stempelt den geschriebenen
Eintrag damit, wie Samba es auf seinem eigenen Schreibweg tut; sonst erführe ein sekundärer
Nameserver nie, dass es etwas zu holen gibt.

**Standorte und Dienste** decken Standorte, Subnetze, Standortverknüpfungen und die Server
je Standort ab: anlegen, umbenennen, beschreiben, löschen, Subnetze einem Standort zuordnen
oder wieder lösen, Kosten und Replikationsintervall der Verknüpfungen, Domänencontroller
zwischen Standorten verschieben. Replikationsverbindungen werden nur angezeigt — die baut
der KCC selbst, und was man dort von Hand ändert, macht er beim nächsten Lauf rückgängig.
Standorte liegen in der Konfigurationspartition und gelten damit in der gesamten
Gesamtstruktur; das Löschen eines Standorts wird verweigert, solange noch ein DC oder ein
Subnetz darauf zeigt.

**Gruppenrichtlinien** sind der erste Teil, der nicht mehr allein über LDAP läuft: Eine GPO
besteht aus einem Verzeichnisobjekt und einem Verzeichnisbaum auf der SYSVOL-Freigabe, und
nichts erzwingt, dass die beiden übereinstimmen. SAMADCON legt sie in der Reihenfolge an, die
`samba-tool gpo create` verwendet — Objekt, Dateien, dann die aus dem Objekt abgeleiteten
SYSVOL-Rechte — und rollt bei einem Fehler die früheren Schritte zurück. Dazu Verknüpfungen
mit Reihenfolge, Erzwingung und Vererbungssperre, die Sicherheitsfilterung, und ein
Konsistenzbericht, den GPMC nicht kennt: Weicht die Version in `GPT.INI` von `versionNumber`
ab, lesen Clients die Richtlinie entweder nie neu oder bei jeder Anmeldung — und nichts sonst
sagt es einem.

Anlegen, Kopieren, Sichern, Wiederherstellen und Löschen stehen in der Oberfläche. Das Löschen
fragt nach und wird abgelehnt, solange noch Verknüpfungen auf die Richtlinie zeigen — die liegen
auf den Containern und müssen dort entfernt werden, was jede Konsole so hält.

Ist der Container mit `SAMADCON_DC_HOSTS` auf eine **IP-Adresse** gesetzt, fragt SAMADCON den DC
vor der Anmeldung nach seinem eigenen Namen und verbindet sich vorrangig darüber. Das ist keine
Kosmetik: Kerberos stellt Tickets für `ldap/<Hostname>@REALM` aus, und für eine nackte Adresse
gibt es keinen solchen Prinzipal. Ohne diesen Schritt scheitert die Anmeldung erst beim Bind,
mit `NT_STATUS_INVALID_PARAMETER` und ohne jeden Hinweis auf den Namen.

### Der Richtlinien-Editor

**Administrative Vorlagen** (4a) liest SAMADCON aus dem Central Store auf SYSVOL —
`.admx` samt sprachpassender `.adml`, einmal je Domäne geparst und gecacht — und erzeugt daraus
die Eingabemasken. Beim Schreiben übernimmt Sambas `RegistryGroupPolicies` die `Registry.pol`,
die `GPT.INI` und `versionNumber`; SAMADCON steuert zwei Dinge bei, die es nicht tut: die
Registrierung der Client-Erweiterung in `gPCMachineExtensionNames` und deren vorgeschriebene
Sortierung. Eine Richtlinie, deren Werte geschrieben, deren CSE aber nicht eingetragen ist,
wird von keinem Client gelesen — sichtbar in jeder Konsole, wirkungslos, ohne Fehlermeldung.

Nachgewiesen ist das nicht am geschriebenen Dateiinhalt, sondern am Client: `gpresult /h` auf
einem domänengejointen Windows 11 führt die Richtlinie unter *Applied GPOs* mit
*Extensions Configured: Registry* und *Revision: AD (9), SYSVOL (9)*, meldet die Registry-CSE
unter *Component Status* als **Success** und zeigt die Einstellung unter *Administrative
Templates* als **Enabled**. Formal korrekt geschriebene Dateien sind nicht dasselbe wie
angewandte Richtlinien — das ist der Unterschied, den nur dieser Test sieht.

Zwei Formatdetails, gegengeprüft an einer von GPMC erzeugten Richtlinie statt aus der
Spezifikation abgeleitet: Ein „Aus", das ADMX als `<delete/>` ausdrückt, schreibt einen
**echten Eintrag** `**del.<Name>` (REG_SZ, ein Leerzeichen) — der Marker sagt dem Client, den
Wert wegzuwerfen, den er vielleicht schon hat. Und in `versionNumber` steht die
**Computerversion im niedrigen Halbwort**, die Benutzerversion im hohen.

Der Richtlinienbaum folgt der **Sprache der Oberfläche**: auf Deutsch liest SAMADCON die Texte
aus `de-DE`, auf Englisch aus `en-US`. Die Definitionen selbst enthalten keinen einzigen
sichtbaren Text — jeder Name im Baum kommt aus einem Sprachverzeichnis, weshalb das die ganze
Übersetzung ist. Fehlt das gewünschte Verzeichnis, nimmt der Server dieselbe Sprache aus einer
anderen Region, sonst Englisch — und **sagt es**: der Editor zeigt dann, welche Sprache
tatsächlich verwendet wurde und dass das passende Sprachpaket fehlt. Ein Baum ohne Beschriftung
wäre die schlechtere Antwort, ein stiller Rückfall die verwirrendere.

Wird eine Einstellung auf *Aktiviert* gestellt, füllt der Editor leere Eingaben mit den
Standardwerten aus der Vorlage — wie GPMC. Das ist keine Kosmetik: Wer `defaultValue` schreibt,
meint *diesen Wert*, und ein leeres Feld schreibt gar nichts. Sonst aktiviert man eine
Richtlinie, deren Optionen ungesetzt bleiben, und der Unterschied fällt erst auf, wenn ein
Client sich anders verhält als erwartet. Bereits gesetzte Werte bleiben unberührt.

Hochgeladene Vorlagen werden **vor** dem Schreiben geprüft, und ein Paket landet ganz oder gar
nicht: Windows liest den Central Store als Ganzes und gibt bei einer einzigen unlesbaren Datei
**jede** administrative Vorlage der Domäne auf — der Gruppenrichtlinienbericht zeigt dann
domänenweit einen Parserfehler statt der Einstellungen. Geprüft wird deshalb, was diesen
Unterschied macht: wohlgeformtes XML, das richtige Wurzelelement, das oft vergessene
`<resources>`, bei einer `.admx` der eigene Namensraum und bei einer `.adml` die vom Schema
verlangte Kopfzeile `<displayName>` und `<description>` vor `<resources>`. Fehlt letztere,
meldet Windows *„Expected `<displayName>`, but found `<resources>`"* — ein Fehler, der auf das
Element zeigt, das da ist, statt auf das fehlende.

Ein Windows-Client, der den Central Store gelesen hat, hält die Vorlagen mit einem Lease offen,
das Schreiben verweigert — auch lange nach der Richtlinienaktualisierung. Ein Hochladen läuft
dann in `file_in_use`, und der sonst greifende Umweg „löschen statt überschreiben" hilft nicht,
weil das Lease auch das Löschen verweigert. Sichtbar mit `smbstatus --locks` auf dem DC; das
Lease löst sich von selbst, `smbcontrol smbd close-share sysvol` oder ein Neustart von
`samba-ad-dc` beendet es sofort.

**Sicherheitseinstellungen** (4b) liegen in `GptTmpl.inf`, einer INI in UTF-16LE mit BOM:
Kennwort- und Kontosperrrichtlinie, Kerberos-Richtlinie, die Überwachungskategorien, das
Zuweisen von Benutzerrechten und eingeschränkte Gruppen. Drei Details stammen aus einer von GPMC
geschriebenen Datei statt aus einer Überlegung, und jedes widerspricht einem der *anderen*
Richtlinienformate dieses Projekts — was das ganze Argument dafür ist, erst eine echte Datei zu
lesen. Es gibt keine Präambel, wo `scripts.ini` mit einer Leerzeile beginnt. Leere Abschnitte
werden ausgeschrieben, wo `scripts.ini` sie weglässt. Und um das Gleichheitszeichen stehen
Leerzeichen — überall außer in `[Unicode]` und `[Version]`.

**Sambas eigene Richtlinien** (4c) sind die, die `samba-gpupdate` auf Linux-Domänenmitgliedern
anwendet: sudo-Rechte, symbolische Links, motd und issue, OpenSSH-Einstellungen und
PAM-Zugriffssteuerung. Windows-Clients ignorieren sie vollständig, der Nachweis läuft deshalb über
`samba-gpupdate --rsop` auf einem Mitglied statt über einen `gpresult`-Bericht. Eine
Client-Erweiterung wird für sie bewusst **nicht** registriert: `samba-tool gpo manage` tut es auch
nicht, und `samba-gpupdate` führt ohnehin jede geladene Erweiterung gegen jede zutreffende
Richtlinie aus.

**Preferences** (4d) decken zehn Typen in drei Wellen ab: Laufwerkzuordnungen,
Registrierungswerte, Dateien, Ordner, Verknüpfungen, Umgebungsvariablen, Drucker, lokale Benutzer
und Gruppen, Dienste und geplante Aufgaben. Jeder Typ hat eine **eigene** CSE-GUID, jeder wurde
deshalb einzeln als angewandt nachgewiesen — ein Nachweis trägt den anderen nicht. Zwei Dinge
haben die Referenzdateien schlicht widerlegt: Es gibt keine gemeinsame Tool-GUID für Preferences,
jeder Typ bringt seine eigene mit; und jeder Typ registriert **zwei** Gruppen, sein eigenes Paar
plus eines in einer gemeinsamen `{00000000-…}`-Gruppe, die Windows *Group Policy Infrastructure*
nennt.

Geplante Aufgaben werden gelesen, bearbeitet und entfernt, aber hier **nicht angelegt**. Eine
Aufgabe im V2-Format trägt einen ganzen Baum — Registrierungsinfo, Prinzipale, Trigger, Aktionen
und achtzehn Einstellungen —, und den ohne Beleg für jeden Teil aus dem Nichts zu schreiben, wäre
genau die Vermutung, die dieses Projekt nicht anstellt. Eine vorhandene Aufgabe bleibt vollständig
erhalten und bearbeitbar.

Die **Zielgruppenadressierung auf Elementebene** wird angezeigt und nicht angefasst. Sie bei jedem
Speichern mitzuschicken hieße, dass ein Umbenennen den Filter löschen kann, der bestimmt, für wen
ein Laufwerk verbunden wird — lautlos und in die freizügige Richtung. Ein gespeichertes Kennwort
(`cpassword`, verschlüsselt mit einem Schlüssel, den Microsoft 2014 veröffentlicht hat) wird
durchgereicht, wo es vorhanden ist, und kann von hier aus nie angelegt werden.

**Skripte** (4e) liegen in `scripts.ini` und `psscripts.ini` je Hälfte, **UTF-16LE
mit BOM und CRLF**. Als UTF-8 gespeichert liest der Client Buchstabensalat und führt nichts
aus — ohne Meldung. Innerhalb eines Abschnitts sind die Einträge nummerierte Paare, und die
Nummern *sind* die Ausführungsreihenfolge: sie müssen lückenlos bei null beginnen, weil Windows
beim ersten fehlenden Index aufhört. Umsortieren, Löschen und Hinzufügen sind deshalb dieselbe
Operation — SAMADCON schreibt immer die ganze Liste eines Ereignisses.

Zwei Details stammen aus einer von GPMC erzeugten Datei statt aus der Spezifikation, und beide
sähen sonst in jedem Diff wie eine Änderung aus, die niemand vorgenommen hat: zwischen BOM und
erstem Abschnitt steht eine **Leerzeile**, und ein Ereignis ohne Skripte bekommt **gar keinen
Abschnitt**, nicht etwa einen leeren. Der Unit-Test dazu vergleicht unsere Ausgabe Byte für Byte
mit dieser Datei.

Wird das letzte Skript einer Hälfte entfernt, trägt SAMADCON die Client-Erweiterung wieder aus.
Bliebe sie stehen, holte jeder Client die Richtlinie bei jeder Aktualisierung und fände nichts
darin.

Die **Ordnerumleitung** (ebenfalls 4e) schreibt `User/Documents & Settings/fdeploy1.ini`, und
deren Format widerspricht jedem anderen hier: Die Datei beginnt mit einer Leerzeile, fünf
Leerzeichen und noch einer Leerzeile; der Versionsabschnitt heißt klein geschrieben `[version]`;
und ein leerer Wert wird als `Key =` ohne abschließendes Leerzeichen geschrieben. Jedes dieser
Details wurde von einer GPMC-Datei abgelesen, und jedes war im ersten Anlauf falsch.

**Windows versteckt seine Richtliniendateien.** `scripts.ini`, `fdeploy1.ini` und `fdeploy.ini`
tragen das DOS-Attribut `HIDDEN`, `fdeploy.ini` zusätzlich `READONLY`. Das hat zwei Folgen, die
beide nicht wie das aussehen, was sie sind:

Eine Verzeichnisauflistung muss **ausdrücklich nach versteckten und System-Einträgen fragen** —
sonst fehlen genau diese Dateien, ohne dass etwas fehlschlägt. Der Einstellungsreport zeigte
dann eine Richtlinie als leerer, als sie ist. SAMADCON übergibt dieselbe Maske wie Sambas eigene
`ntacls`- und `gpo`-Werkzeuge.

Und `savefile()` öffnet zum Überschreiben mit normalen Attributen, was SMB bei einer versteckten
Datei **mit `ACCESS_DENIED` ablehnt** — eine Meldung, die zum Prüfen von ACLs verleitet, die
völlig in Ordnung sind. SAMADCON öffnet stattdessen mit `FILE_OVERWRITE_IF` und nennt dabei die
Attribute, die die Datei bereits hat; die Disposition kürzt selbst. Kein `truncate`: das ist in
den Python-Bindungen ein SMB1-Aufruf und scheitert gegen eine SMB3-Verbindung mit
`NT_STATUS_REVISION_MISMATCH`. Klappt auch das nicht, wird die Datei ersetzt — das kostet die
Attribute und steht als Warnung im Protokoll, denn ein Editor, der eine von GPMC angelegte
Richtlinie gar nicht bearbeiten kann, ist das schlechtere Ergebnis.

Gefunden wurde beides erst an einer echten, von GPMC erzeugten Richtlinie. Die Integrationstests
legen ihre GPOs selbst an, und deren Dateien haben normale Attribute — sie prüfen SAMADCON gegen
SAMADCON. Die Schreibpfade sind deshalb zusätzlich als Unit-Tests abgesichert, mit einer Attrappe
statt eines Domänencontrollers.

Die SMB-Verbindung braucht eine **s3-LoadParm** (`samba.samba3.param`), nicht die aus
`samba.param`, die SamDB nimmt. Mit der falschen antwortet `libsmb` mit
`NT_STATUS_INVALID_PARAMETER_MIX`, ohne den Parameter zu nennen. `samadconctl sysvol` prüft
diesen Pfad einzeln.

Die **Sicherung** ist ein ZIP mit dem SYSVOL-Baum und den beiden `.SAMBAEXT`-Dateien unter
Sambas eigenen Namen. Entpackt nimmt `samba-tool gpo restore` das Archiv an — gegengeprüft,
nicht angenommen. Eine leere `.SAMBAEXT`-Datei wird dabei nicht geschrieben: LDB lehnt ein
Attribut ohne Wert ab, und ein Archiv mit einer solchen Datei ließe sich mit `samba-tool`
überhaupt nicht einspielen.

Vom Editorbaum, den GPMC zeigt, bleiben vier Zweige bewusst draußen: *Software installation*,
*Name Resolution Policy*, *Deployed Printers* und *Policy-based QoS*. Sie kommen dazu, wenn sie
gebraucht werden. Eine kleine Abweichung innerhalb des Gebauten: den GPMC-Knoten
*Alle Einstellungen*, der alles flach auflistet, gibt es nicht; dorthin führt die Suche.

Der Einstellungsreport zeigt jede Richtlinie mit dem, was auf SYSVOL steht. Dass die
**Default Domain Policy einer Samba-Domäne dabei leer erscheint, ist richtig**: Samba legt sie
mit leeren Ordnern `MACHINE` und `USER` an und schreibt keine `GptTmpl.inf`. Die
Kennwortrichtlinie liegt am Domänenobjekt im Verzeichnis — dort liest sie die Diagnose, und
dort bearbeitet sie auch `samba-tool domain passwordsettings`. Bei einer aus Windows
gewachsenen Domäne steht in derselben Richtlinie dagegen eine Sicherheitsvorlage.

**Diagnose** ist durchgehend lesend: Domänencontroller mit Standort und GC-Kennzeichen, die
sieben Betriebsmasterrollen samt Inhaber, Funktionsebenen, der Replikationsstand des
verbundenen DCs aus `repsFrom`, die Kennwort- und Sperrrichtlinie einschließlich
differenzierter Richtlinien (PSOs) sowie gesperrte, deaktivierte und abgelaufene Konten.
Rollen zu übernehmen oder Replikation zu erzwingen gehört bewusst nicht dazu — dafür gibt es
`samba-tool fsmo seize` und `samba-tool drs replicate` auf dem DC.

## Aufbau

```
backend/samadcon/     FastAPI-Anwendung
  core/               Executor (ein Worker-Thread je Sitzung), Audit, Fehlerübersetzung, Ratelimit
  auth/               Kerberos-TGT, krb5.conf für mehrere Realms, Sessions, CSRF
  ad/                 LDAP-Zugriff: Verbindungsziele, Server-Probe, Verzeichnis, ACLs
  gpo/                GPC/SYSVOL, ADMX, Registry.pol, Security-INF, Preferences, VGP
  api/v1/             HTTP-Router
frontend/src/         React + TypeScript (MMC-artiges Layout)
frontend/public/      Favicon
frontend/src/assets/  Lockup und Bildmarke, je hell/dunkel, dazu einfarbig
docker/               Dockerfile, Entrypoint, nginx, supervisord
docs/brand/           Bannervarianten, von der Oberfläche nicht verwendet
```

Die Samba-Python-Bibliotheken sind blockierend und nicht threadsicher. Alle Samba-Aufrufe laufen
deshalb ausschließlich über `samadcon/core/executor.py` (Threadpool mit Sperre je Sitzung) — nie
direkt aus einem Router.

## Technische Grundlage

Der GPO-Teil stützt sich auf bestehende Samba-Bausteine statt auf Nachbauten:

- `samba.policies.RegistryGroupPolicies` — schreibt Registry.pol, hält GPT.INI und LDAP
  `versionNumber` synchron und registriert CSE-GUIDs.
- `samba.dcerpc.preg` + `ndr_pack`/`ndr_unpack` — PReg-Format für Sonderfälle.
- `samba.gp_parse.*` — Parser für GptTmpl.inf, scripts.ini, \*.pol.
- `samba.netcmd.gpo` — Referenz für GPO-Anlage inkl. `dsacl2fsacl()` (SYSVOL-ACLs).

## Entwicklung

Backend lokal (benötigt `python3-samba` aus der Distribution):

```bash
python3 -m venv --system-site-packages .venv && .venv/bin/pip install -e "backend[dev]"
```

Tests ohne DC — laufen auch ohne `python3-samba` und ohne Container:

```bash
.venv/bin/pytest backend/tests/unit -q
```

## Lizenz

AGPL-3.0-or-later.
