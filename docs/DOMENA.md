# Własna domena dla Winq

Domena idzie **tylko na landing** (`iskra-landing`: strona, konta, płatności). Boty zostają na swoich adresach
`*.onrender.com` / `*.fly.dev`. Klient wchodzi do bota z konta („Panel”), jednorazowym linkiem SSO, więc nie widzi
adresu bota i nie musi go pamiętać.

## Jak landing i boty są połączone
- Landing trzyma dla każdego konta adres bota (`instance_url`) i jego klucz `SSO_SECRET`.
- „Panel” na landingu tworzy link ważny 60 s, podpisany tym kluczem, wystawiony na adres bota.
- Bot ma `CONTROL_ORIGIN`, czyli adres landingu, na który prowadzi przycisk „Zaloguj się przez konto Winq”.

Zmiana domeny landingu nie dotyka SSO (link jest wystawiany na adres bota, a ten się nie zmienia).

## Kolejność (żeby nic nie przestało działać)
1. Render → `iskra-landing` → **Settings → Custom Domains → Add**: `twojadomena.pl`.
2. DNS u rejestratora, dokładnie z wartościami, które pokaże Render. Zwykle:
   - `@` A `216.24.57.1` (albo ALIAS/ANAME na `iskra-landing.onrender.com`),
   - `www` CNAME `iskra-landing.onrender.com`,
   - usuń stare rekordy A/AAAA dla `@` (parking rejestratora). Na Cloudflare: „DNS only” (szara chmurka).
3. Render → **Verify**. Czekaj, aż `https://twojadomena.pl` otworzy stronę z kłódką.
4. Dopiero wtedy: `iskra-landing` → **Environment** → `PUBLIC_ORIGIN=https://twojadomena.pl` (bez `/` na końcu) → deploy.
   Od tej chwili linki w mailach, powroty ze Stripe, ciasteczka, sitemap i podgląd linku używają nowej domeny,
   a stary adres `iskra-landing.onrender.com` i `www.` przekierowują przeglądarkę na nią (ścieżka i parametry
   zostają, więc działają też stare linki do resetu hasła).
5. Na każdym istniejącym bocie (także Twoim): `CONTROL_ORIGIN=https://twojadomena.pl` → deploy. Bez tego działa
   dzięki przekierowaniu, ale z jednym zbędnym skokiem. Nowe boty dostają nowy adres same.
6. Stripe → **Developers → Webhooks**: zmień adres endpointu na `https://twojadomena.pl/stripe/webhook`
   (edycja istniejącego endpointu zachowuje klucz podpisu). Stary adres też dalej przyjmuje webhooki.

## Czego nie robić
- Nie ustawiaj `PUBLIC_ORIGIN` przed działającym HTTPS na domenie: landing przyjmuje formularze tylko z adresu
  w `PUBLIC_ORIGIN`, a przekierowanie wysłałoby wszystkich na niedziałającą stronę.
- Nie podpinaj własnych domen pod boty klientów. Adres bota jest zapisany w koncie (`instance_url`) i w jego
  `PUBLIC_ORIGIN`; zmiana tylko jednego z nich psuje logowanie z konta.
- Nie wyłączaj adresu `*.onrender.com` landingu: zostaje dla webhooków i wywołań administracyjnych.
- Nie zmieniaj `SSO_SECRET` botów ręcznie.

Klienci zalogowani na starym adresie zalogują się raz ponownie na nowej domenie (ciasteczko jest przypisane do adresu).
