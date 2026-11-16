# Instancje klientów (opcja 4: osobny serwer dla każdego)

Każdy klient dostaje własną kopię aplikacji: osobny serwis na Renderze, osobny dysk z bazą, osobne sekrety.
Dane i tokeny jednego klienta nigdy nie są w tym samym procesie ani bazie co dane innego.

## Jak chroniony jest token Tindera
- Klient wkleja token w swoim panelu (Ustawienia → Tinder). Serwer najpierw sprawdza go w Tinderze, dopiero potem zapisuje.
- Zapis: AES-256-GCM w bazie klienta. Klucz to `TOKEN_ENCRYPTION_KEY` tylko tej instancji. Sama kopia bazy niczego nie zdradza.
- Bez klucza serwer odmawia zapisu (fail closed). Tekst jawny nigdy nie trafia na dysk.
- Token nie wraca do przeglądarki i nie jest logowany. Panel pokazuje tylko końcówkę odcisku SHA-256.
- „Usuń token i rozłącz" kasuje zaszyfrowany token i wyłącza połączenie. Wylogowanie z tinder.com unieważnia token po stronie Tindera.
- Rotacja klucza: nowy klucz w `TOKEN_ENCRYPTION_KEY`, stary w `TOKEN_ENCRYPTION_KEY_OLD`; token zostanie przeszyfrowany przy następnym odczycie.
- `TINDER_AUTH_TOKEN` w zmiennych środowiskowych zostaje tylko dla instancji właściciela. U klientów go nie ustawiamy.

## Założenie nowej instancji
1. `python scripts/new_customer.py <slug>` i zachowaj wynik w menedżerze haseł.
2. Na Renderze: nowy Web Service z tego repozytorium (gałąź `main`), plan jak instancja właściciela, dysk 1 GB na `/var/data`.
3. Ustaw zmienne z kroku 1 oraz `ANTHROPIC_API_KEY`. Deploy.
4. Przekaż klientowi adres panelu i `DASHBOARD_TOKEN` bezpiecznym kanałem.
5. Klient loguje się, wkleja token Tindera, ustawia styl i cel.

## Czego to nie rozwiązuje
- Operator (my) z dostępem do Rendera ma dostęp i do dysku, i do klucza danej instancji. Zawsze włączona automatyzacja wymaga, żeby serwer umiał odszyfrować token. Ogranicz dostęp do workspace Rendera do minimum i włącz 2FA.
- Instancje na tym samym dostawcy mogą wychodzić z podobnych adresów IP. Zachowujemy konserwatywne limity (30/min, 300/h) i obserwujemy, czy Tinder nie ogranicza kont.
- Integracja jest nieoficjalna i łamie regulamin Tindera; klient akceptuje to ryzyko dla swojego konta.

## Statystyki, podsumowanie tygodnia i kontrola floty

**Statystyki w panelu** (zakładka „Statystyki") liczą się w przeglądarce z danych, które bot sam synchronizuje z Tindera
(wiadomości, profile, plan rozmowy). Nic nie trzeba konfigurować per instancja. Pasek na górze zakładki pokazuje, czy
połączenie działa i kiedy była ostatnia synchronizacja (ostrzega po 30 min ciszy, przy błędzie tokenu, przy wstrzymanym agencie).

**Podsumowanie tygodnia** wysyła serwis kontrolny (niedziela 20:00 czasu warszawskiego, doganianie do wtorku 20:00):
1. Serwis pyta bota klienta o `GET /internal/summary`. Zapytanie jest podpisane `SSO_SECRET` tej instancji
   (HMAC, ważne 2 minuty), więc odpowie tylko serwisowi kontrolnemu. Odpowiedź to **same liczby i kody stanu**, bez imion i treści rozmów.
2. Z odpowiedzi powstaje mail: status (czy wszystko działa), cztery liczby ze zmianą wobec poprzedniego tygodnia, co czeka na klienta
   i przycisk „Zobacz pełne statystyki" → `/konto/panel?view=stats` (po zalogowaniu wprost w zakładce Statystyki).
3. Konto jest „zajmowane" w bazie przed wysyłką i oznaczane jako wysłane dopiero po przyjęciu maila przez SMTP, więc restart, dwa procesy
   ani ponowienie nie wyślą dwóch maili. Bot, który nie odpowiada, jest ponawiany co 30 minut do wtorku 20:00, potem tydzień jest pomijany.
4. Klient wypisuje się linkiem w mailu (jedno kliknięcie, także nagłówek `List-Unsubscribe`) albo checkboxem na stronie konta.

Ustawienia serwisu kontrolnego: `WEEKLY_SUMMARY=false` wyłącza pętlę (domyślnie włączona; działa tylko przy skonfigurowanym SMTP i `PUBLIC_ORIGIN`).
Nowe konta dostają pierwsze podsumowanie po 3 dniach.

**Kontrola floty** (token `ADMIN_TOKEN`):
```bash
# stan każdego bota tak, jak on sam go widzi: osiągalny, Tinder połączony, świeża synchronizacja, agent działa
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" https://<serwis-kontrolny>/admin/fleet
# podgląd, co i do kogo poszłoby teraz (nic nie wysyła i nie zapisuje)
curl -s -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -d '{"dry_run":true,"force":true}' https://<serwis-kontrolny>/admin/weekly/run
# wysłanie teraz jednej osobie, poza harmonogramem
curl -s -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -d '{"force":true,"email":"ktos@example.com"}' https://<serwis-kontrolny>/admin/weekly/run
```
`/admin/fleet` oznacza jako problem bota, który nie odpowiada (np. stara wersja bez `/internal/summary`), ma błąd tokenu Tindera,
nieświeżą synchronizację (>6 h) albo błąd pracy w tle. `/admin/accounts` pokazuje dla każdego konta `weekly_sent_at` i `weekly_note`.

**Nowe instancje** dostają wszystko, czego to wymaga, z `provision.instance_env` (`SSO_SECRET`, `CONTROL_ORIGIN`, `WORKER_ENABLED`, limity Tindera),
a test `tests/test_fleet_contract.py` uruchamia bota dokładnie z takimi ustawieniami i sprawdza, że odpowiada serwisowi kontrolnemu
i przyjmuje link logowania.

**Istniejące instancje** dostają nowy panel i `/internal/summary` dopiero po aktualizacji obrazu: po scaleniu do `main` GitHub Actions buduje
obraz Fly (`:latest` dla nowych klientów), a istniejące boty przesuwasz `POST /admin/fly/update-image`. Instancje na Renderze mają
`autoDeployTrigger: off`, więc trzeba je wdrożyć ręcznie. Do tego czasu `/admin/fleet` pokaże je jako nieosiągalne, a podsumowanie
dla ich właścicieli się nie wyśle (bez błędu dla klienta).

## Automatyczny rollout nowych wersji botów (co noc o 3:00)

Serwis kontrolny sam przestawia boty na najnowszą zbudowaną wersję. Nie trzeba już ręcznie wołać `/admin/fly/update-image`.

- **Skąd wie, co jest najnowsze:** z ostatniego udanego przebiegu workflow „Fly bot image” na `main` (repozytorium jest publiczne, więc GitHub API
  nie wymaga sekretu). Obraz to `registry.fly.io/<aplikacja>:git-<12 znaków commita>`.
- **Co jest nieaktualne:** bot, któremu serwis nie zapisał jeszcze tej wersji (tabela `rollout_state`). Boty sprzed tej funkcji dostają ją przy pierwszym przebiegu.
  Nowo utworzony bot jest od razu oznaczony jako aktualny.
- **Kiedy:** raz na noc w oknie 3:00-5:00 czasu warszawskiego (początek zapisywany, więc nie powtarza się tej samej nocy, nawet po awarii).
  `ROLLOUT=false` na serwisie kontrolnym wyłącza harmonogram.
- **Kolejność:** boty Fly (od najstarszego konta), potem boty klientów na Renderze, na końcu Twój własny bot (`OWNER_SERVICE_ID`).
- **Bezpieczeństwo:** jeden bot naraz z przerwą. Bot Fly musi wstać jako `live` i odpowiedzieć na podpisane zapytanie `/internal/summary`, zanim
  ruszy następny. Przy pierwszej awarii serwis cofa ten bot do dokładnie poprzedniego obrazu (po digeście, nie po `:latest`), **zatrzymuje cały przebieg**
  i wysyła mail na `OWNER_EMAIL`. Konta bez aktywnej subskrypcji są pomijane (ich bot jest wyłączony), a po wznowieniu dostaną nową wersję następnej nocy.
  Zły build na Renderze zostawia starą wersję (Render nie podmienia jej przy `build_failed`), wtedy tylko alert.

```bash
# stan: docelowa wersja, które boty są za nią, czy trwa przebieg
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" https://winq.site/admin/rollout
# podgląd, co zostałoby zaktualizowane (nic nie rusza)
curl -s -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -d '{"dry_run":true}' https://winq.site/admin/rollout/run
# uruchom teraz (w tle), a {"force":true} przestawia też boty, które są już aktualne
curl -s -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -d '{}' https://winq.site/admin/rollout/run
```
Pierwszej nocy po wdrożeniu tej funkcji przestawią się **wszystkie** istniejące boty. Warto wcześniej zrobić `dry_run`, żeby zobaczyć listę.
