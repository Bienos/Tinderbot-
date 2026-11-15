# Boty klientów na Fly.io

Nowi klienci mogą dostawać bota na Fly.io zamiast na Renderze. Izolacja zostaje taka sama: każdy klient ma
własną aplikację, maszynę, bazę na własnym dysku i własne klucze. Zmienia się koszt: najmniejsza maszyna
(256 MB, zawsze włączona) plus dysk 1 GB to ok. 2,3–2,6 USD miesięcznie zamiast ok. 7,25 USD na Renderze.

## Jak to działa
- Aplikacja `winq-u<numer>-<losowe>` (przedrostek z nazwy marki) z adresem `https://<nazwa>.fly.dev` (HTTPS daje Fly).
- Dysk 1 GB w regionie `fra` (Frankfurt), szyfrowany, z codzienną kopią trzymaną 7 dni.
- Maszyna 256 MB, zawsze włączona (bot pracuje także wtedy, gdy panel jest zamknięty).
- Hasła i klucze (token panelu, klucz szyfrowania, klucz SSO, klucz modelu) trafiają do sekretów aplikacji Fly,
  nigdy do zwykłej konfiguracji maszyny.
- Ustawienia modelu są kopiowane z Twojego bota na Renderze (`INSTANCE_TEMPLATE_SERVICE_ID`), więc klucz modelu
  nie leży w ustawieniach strony.
- Gdy subskrypcja wygaśnie, maszyna jest zatrzymana i nie uruchomi się sama. Po wznowieniu startuje znowu.
- Obecni klienci zostają na Renderze. Każdy bot pamięta, gdzie działa (`fly:<nazwa>` albo identyfikator Rendera).

## Ustawienie (raz)
1. Konto na fly.io i karta w Billing.
2. Token organizacji: panel Fly, wybierz organizację, **Tokens**, utwórz token organizacji. Skopiuj cały ciąg
   zaczynający się od `FlyV1`. Nie wklejaj go do czatu ani do plików w repozytorium.
3. Aplikacja na obrazy: `iskra-obraz-e96u` (wpisana w `.github/workflows/fly-image.yml`; inną nazwę można podać zmienną
   repozytorium `FLY_IMAGE_APP`). Nie uruchamia żadnej maszyny, tylko przechowuje obraz bota.
4. GitHub, repozytorium, **Settings → Secrets and variables → Actions**: sekret `FLY_API_TOKEN` (token z kroku 2).
   Potem **Actions → Fly bot image → Run workflow**. Obraz buduje się sam po każdej zmianie bota na `main`.
5. Render, `iskra-landing`, **Environment**:
   - `FLY_API_TOKEN`: ten sam token,
   - `FLY_ORG`: nazwa organizacji (dla konta osobistego zwykle `personal`),
   - `FLY_IMAGE`: `registry.fly.io/iskra-obraz-e96u:latest`,
   - opcjonalnie `FLY_REGION` (domyślnie `fra`) i `FLY_MEMORY_MB` (domyślnie `256`),
   - na końcu `PROVISION_BACKEND=fly`: od tej chwili nowi klienci trafiają na Fly.
   Wymaga ustawionego już `INSTANCE_TEMPLATE_SERVICE_ID` oraz kluczy Rendera (`RENDER_API_KEY`, `RENDER_OWNER_ID`).

Powrót: `PROVISION_BACKEND=render` (albo usunięcie tej zmiennej). Boty już stworzone na Fly działają dalej.

## Aktualizacja botów klientów
Po każdym przebiegu „Fly bot image” podsumowanie pokazuje nazwę obrazu (`registry.fly.io/...:git-<sha>`).
Aby przenieść na niego wszystkich klientów z Fly (po kolei, każdy bot restartuje się na kilka sekund, dane zostają):

```bash
curl -X POST https://iskra-landing.onrender.com/admin/fly/update-image -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" -d '{"image": "registry.fly.io/<aplikacja>:git-<sha>"}'
```

## Co jeszcze trzeba sprawdzić na prawdziwym koncie
- Czy 256 MB wystarcza podczas pełnego importu historii (lokalnie bot zajmował 41 MB w spoczynku, na Renderze
  do 180 MB przy imporcie). Jeśli nie, `FLY_MEMORY_MB=512` (ok. 3,7 USD miesięcznie).
- Pierwsze utworzenie bota przez API, adres `.fly.dev`, logowanie z konta (SSO) i restart.

## Adresy paneli w Twojej domenie (`https://<id>.app.winq.site`)
- Zwrotnica `winq-router` (deploy/router) przyjmuje `*.app.winq.site` i przekazuje każde zapytanie do bota
  `winq-b-<id>` przez sieć Fly (`fly-replay`). Boty nie mają wtedy publicznych adresów.
- Identyfikator w adresie jest losowy i nic nie mówi o kliencie.
- Włączenie: rekordy DNS (niżej), potem w Renderze
  `FLY_PUBLIC_DOMAIN=app.winq.site`. Bez tej zmiennej boty dostają adresy `<aplikacja>.fly.dev`.
- DNS w home.pl (tylko dwa rekordy, bez `_acme-challenge`, bo formularz home.pl nie przyjmuje podkreślnika w nazwie):
  `A *.app -> 66.241.125.201` i `AAAA *.app -> 2a09:8280:1::207:e346:0`.
- Certyfikat: nie wildcard, tylko osobny dla każdego klienta. Provisioning prosi o niego `winq-router`
  (`FLY_ROUTER_APP`) zaraz po utworzeniu bota; wystawienie trwa ok. pół minuty, a bot jest uznany za gotowy
  dopiero, gdy certyfikat ma status Ready.
- Koszt: 2 maszyny zwrotnicy (ok. 4,4 USD) stałe; certyfikaty: pierwsze 10 gratis, potem 0,10 USD miesięcznie za klienta.
- Zwrotnica jest bezstanowa i niczego nie loguje; nazwa marki w `APP_PREFIX` musi zgadzać się z `BRAND_NAME`.
