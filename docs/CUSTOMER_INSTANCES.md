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
