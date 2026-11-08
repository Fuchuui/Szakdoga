# SDN hálózatvezérlő labor

Ez a projekt egy Kathará-alapú hálózati labort és egy FastAPI-vezérlőt tartalmaz. A laborban egy FRRouting-alapú router, egy switch, 20 kliensgép és egy adminisztrátori gép szerepel. A vezérlő HTTP API-n keresztül tudja konfigurálni a routert, illetve egyes műveleteket a Kathará gépein végrehajtani.

## Előfeltételek

- Linux disztribúció (ajánlott: Ubuntu vagy Debian), vagy Windows alatt WSL2 Ubuntu.
- Docker, amelyet a Kathará használ a labor gépeinek futtatására.
- Kathará CLI.
- Python 3 és `venv`.
- A labor indításához elegendő memória és lemezterület a Docker-konténerek számára.

Windows alatt a parancsokat az Ubuntu/WSL terminálban futtasd, ne a PowerShellben. Telepítsd és indítsd el a Dockert a használt Kathará/WSL2 környezethez; a Dockernek ugyanabból a környezetből elérhetőnek kell lennie, ahol a `kathara` parancsot futtatod.

Ellenőrizd a telepítést:

```bash
docker --version
kathara --version
python3 --version
```

A Docker és a Kathará telepítése disztribúciónként eltérhet. Kövesd a Kathará hivatalos telepítési útmutatóját: <https://www.kathara.org/>.

## Telepítés

Klónozd a repót, majd lépj a projekt könyvtárába:

```bash
git clone https://github.com/Fuchuui/Szakdoga.git
cd Szakdoga
```

Hozz létre és aktiválj egy Python virtuális környezetet, majd telepítsd az API függőségeit:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install fastapi uvicorn netmiko
```

A `shared/` könyvtárban lévő Debian csomagokat a router indításkor telepíti a `r1.startup` parancsfájl. Ezek a csomagok Debian-alapú labor-környezethez készültek; ne próbáld őket a saját gépedre telepíteni.

## A labor indítása

A projekt gyökérkönyvtárából indítsd el a Kathará labort:

```bash
kathara lstart
```

Várd meg, amíg a gépek elindulnak. A router induláskor telepíti a `shared/` mappából a DHCP-hez szükséges csomagokat, beállítja az `admin` jelszót, és elindítja az SSH- és FRR-szolgáltatást.

Ellenőrizheted a labor állapotát:

```bash
kathara linfo
```

Az API a routert a `127.0.0.1:2222` címen próbálja elérni SSH-n. A `lab.conf` `r1[port]=2222:22` beállítása és a router SSH-szolgáltatása ezért szükséges; az API-t ugyanabban a gépi/konténeres környezetben futtasd, ahonnan ez a cím elérhető.

## Az API indítása

Aktiváld a virtuális környezetet, ha még nem aktív, majd indítsd el az alkalmazást:

```bash
source .venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8000
```

Az API helyben a <http://127.0.0.1:8000> címen érhető el. Az interaktív dokumentáció:

<http://127.0.0.1:8000/docs>

Az API folyamatának futnia kell, amíg a kéréseket használod. A `--host 127.0.0.1` beállítás csak a saját gépről teszi elérhetővé; ne cseréld `0.0.0.0`-ra biztonsági védelem nélkül.

## Példák

Az alábbi példák Linux/WSL terminálhoz készültek. A kéréseket az API dokumentációjában, a `/docs` oldalon is elküldheted.

### Állapot ellenőrzése

```bash
curl http://127.0.0.1:8000/
curl http://127.0.0.1:8000/router-status
```

### VLAN létrehozása a routeren

Először hozd létre a VLAN interfészt:

```bash
curl -X POST http://127.0.0.1:8000/configure-vlan \
  -H "Content-Type: application/json" \
  -d '{"vlan_id":10,"ip_address":"192.168.10.1","subnet_mask":"24"}'
```

Ezután indítható DHCP-szerver az adott VLAN-hoz:

```bash
curl -X POST http://127.0.0.1:8000/configure-dhcp \
  -H "Content-Type: application/json" \
  -d '{"vlan_id":10,"range_start":"192.168.10.10","range_end":"192.168.10.50"}'
```

A DHCP beállítása előtt konfiguráld a VLAN-t; az API a VLAN-okat a saját memóriájában tartja nyilván.

### Tűzfalszabály hozzáadása

Az `action` értéke `permit` vagy `deny` lehet:

```bash
curl -X POST http://127.0.0.1:8000/configure-firewall \
  -H "Content-Type: application/json" \
  -d '{"source_vlan":10,"destination_vlan":30,"action":"permit"}'
```

### QoS beállítása

```bash
curl -X POST http://127.0.0.1:8000/configure-qos \
  -H "Content-Type: application/json" \
  -d '{"vlan_id":10,"rate_limit":"1mbit"}'
```

### Kliens DHCP-re csatlakoztatása

```bash
curl -X POST http://127.0.0.1:8000/connect-pc \
  -H "Content-Type: application/json" \
  -d '{"pc_name":"pc1","vlan_id":10}'
```

Az API további végpontjai:

| Metódus | Útvonal | Leírás |
|---|---|---|
| `GET` | `/` | API állapot |
| `GET` | `/router-status` | Router interfészeinek lekérdezése |
| `POST` | `/configure-router` | IP-cím beállítása a router `eth0` interfészére |
| `POST` | `/configure-vlan` | VLAN interfész létrehozása |
| `POST` | `/configure-dhcp` | DHCP-szerver indítása egy VLAN-on |
| `DELETE` | `/remove-vlan/{vlan_id}` | VLAN interfész és DHCP-folyamat eltávolítása |
| `POST` | `/configure-firewall` | Tűzfalszabály felvétele |
| `POST` | `/configure-qos` | Sávszélesség-korlát beállítása |
| `POST` | `/connect-pc` | Egy kliensgép csatlakoztatása és DHCP-kérése |
| `POST` | `/connect-pc-range` | Kliensgépek tartományának csatlakoztatási kísérlete |
| `POST` | `/save-config` | Az API memóriabeli állapotának mentése a `configs/` könyvtárba |
| `POST` | `/load-config` | Mentett konfiguráció betöltése és alkalmazása |

A POST végpontok pontos kérésmezőit a `/docs` oldalon találod.

### Konfiguráció mentése és betöltése

Például az aktuális API-állapot mentése `configs/proba.json` fájlba:

```bash
curl -X POST http://127.0.0.1:8000/save-config \
  -H "Content-Type: application/json" \
  -d '{"config_name":"proba"}'
```

Betöltés:

```bash
curl -X POST http://127.0.0.1:8000/load-config \
  -H "Content-Type: application/json" \
  -d '{"config_name":"proba"}'
```

A mentés csak az API futó folyamatának memóriabeli állapotát írja fájlba. Az API újraindításakor ez a memória kiürül; a `/load-config` segítségével alkalmazd újra a korábban elmentett konfigurációt. A konfiguráció betöltéséhez a Kathará labornak és a router SSH-kapcsolatának is működnie kell.

## Leállítás

Az API-t a termináljában `Ctrl+C`-vel állítsd le. A labort a projekt könyvtárából állítsd le:

```bash
kathara lstop
```

## Hibaelhárítás

- **A `/router-status` nem éri el a routert:** ellenőrizd, hogy a labor fut-e (`kathara linfo`), az SSH-szolgáltatás elindult-e, és a `127.0.0.1:2222` port elérhető-e az API környezetéből.
- **A `kathara` parancs vagy a Docker nem található:** telepítsd és konfiguráld a Katharát és a Dockert ugyanabban a Linux/WSL környezetben, majd ellenőrizd a parancsokat.
- **A DHCP-csomag telepítése sikertelen:** ellenőrizd, hogy a labor `shared/` könyvtárában megvannak-e a Debian csomagok, és nézd meg a router indulási naplóját.
- **A DHCP beállítása VLAN-hibát jelez:** előbb hívd meg a `/configure-vlan` végpontot. Az API újraindítása után a VLAN-okat ismét konfigurálni kell, vagy mentett konfigurációt kell betölteni.
- **A kliens nem kap IP-címet:** ellenőrizd, hogy a kliens a megfelelő Kathará hálózathoz csatlakozik-e, a VLAN és a DHCP-pool helyes-e, valamint hogy a DHCP-kiszolgáló fut-e.

## Fontos biztonsági tudnivalók

- A labor jelenleg `admin` jelszót állít be a routeren, az API pedig `root` felhasználóval ezen a jelszón próbál SSH-n csatlakozni. Ez kizárólag helyi, izolált tesztlaborhoz való; ne használd éles környezetben, és ne tedd ki az API-t vagy a router SSH-portját az internetre.
- A `main.py` jelenlegi beállítása rögzített jelszót tartalmaz. Megosztás vagy éles használat előtt cseréld biztonságos, külső konfigurációból olvasott hitelesítésre.
- A tűzfal- és QoS-szabályok a futó routeren módosítanak beállításokat. Kísérletezés előtt győződj meg róla, hogy izolált laborban vagy.
