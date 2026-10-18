# KSeF dla Home Assistanta

> **In English.** KSeF (Krajowy System e-Faktur) is Poland's mandatory national e-invoicing
> system run by the Ministry of Finance: every B2B invoice in Poland is issued and received
> through it. This unofficial integration reads your invoices from the KSeF 2.0 API with a
> read-only token, sends a push notification to your phone when a new purchase invoice
> arrives, and adds a sidebar panel listing purchase and sales invoices with PDF/XML
> download (PDF rendered in the browser by the Ministry's official open-source generator).
> It is aimed at Polish businesses, so the UI and the rest of this README are in Polish.

## 📱 Push na telefon, gdy tylko wpadnie nowa faktura

**Nowa faktura kosztowa w KSeF = powiadomienie na Twoim telefonie, najpóźniej po kwadransie.**
Bez logowania do Aplikacji Podatnika, bez sprawdzania programu księgowego i bez
czekania, aż księgowa da znać. Dostajesz w pushu kontrahenta, kwotę brutto, numer
faktury i datę, a tapnięcie otwiera listę faktur z PDF-em gotowym do pobrania.

```
KSeF: Nowa faktura
Orange Polska S.A.: 123,00 zł brutto
F/12345/10/2026 z 07.10.2026
```

Push może iść na kilka telefonów naraz. Wybierasz je z listy w konfiguracji.

To nieoficjalna integracja Home Assistanta z **Krajowym Systemem e-Faktur (KSeF 2.0)**.
Poza pushami daje panel w menu bocznym z fakturami zakupowymi i sprzedażowymi
z poprzedniego i bieżącego miesiąca. To nie jest program księgowy, tylko podgląd
i powiadomienia.

## ⚠️ Token KSeF wyłącznie do odczytu faktur

Integracja loguje się **tokenem KSeF**. Generując go, zaznacz **tylko jedno uprawnienie:
„przeglądanie faktur”**. Nic więcej nie jest potrzebne.

Token z dodatkowymi uprawnieniami, np. „wystawianie faktur” albo „zarządzanie
uprawnieniami”, pozwalałby każdemu, kto go zdobędzie (z kopii zapasowej Home Assistanta,
przejętego serwera albo przez pomyłkę wklejony w niewłaściwe miejsce), **wystawiać faktury
w Twoim imieniu albo nadawać innym dostęp do Twojego KSeF**. Token z samym odczytem
ogranicza ewentualny wyciek do wglądu w faktury.

Jak wygenerować token:

1. Wejdź na **https://ap.ksef.mf.gov.pl** (Aplikacja Podatnika KSeF) i zaloguj się
   przez login.gov.pl: profil zaufany, mObywatel, bank albo e-dowód.
2. Wybierz kontekst swojego **NIP-u**.
3. **Tokeny → Generuj token**. Nadaj nazwę, np. „Home Assistant”, i zaznacz
   **tylko „przeglądanie faktur”**.
4. Kliknij **Generuj token**, a gdy proces się zakończy, **Kopiuj**. Token jest pokazywany
   **tylko raz** i zawiera znaki `|`, więc skopiuj go w całości.

Token nie wygasa, dopóki go nie unieważnisz (Tokeny → Lista tokenów). Gdy KSeF
go odrzuci, Home Assistant poprosi o nowy.

## Funkcje

- **Panel „KSeF” w menu bocznym**: faktury zakupowe i sprzedażowe, przełącznik
  poprzedni/bieżący miesiąc, kwoty netto i brutto, sumy, ręczne odświeżanie.
- **Pobieranie PDF i XML** każdej faktury. PDF generuje w przeglądarce oficjalny
  generator wizualizacji Ministerstwa Finansów, z kodem QR weryfikacji.
- **Powiadomienia push, które nie giną**: gdy telefon jest chwilowo niedostępny albo
  Home Assistant właśnie się restartuje, push czeka w kolejce i jest ponawiany co minutę
  (do 24 godzin). Każdy telefon dostaje go dokładnie raz.
- **Powiadomienia push** o nowych fakturach zakupowych (opcjonalnie także sprzedażowych)
  na jeden albo kilka telefonów z aplikacją Home Assistanta lub przez inną usługę `notify`.
  Tapnięcie powiadomienia otwiera panel.
- **Zdarzenie `ksef_new_invoice`** dla własnych automatyzacji.
- **Sensory**: liczba faktur zakupowych i sprzedażowych w bieżącym miesiącu,
  w atrybutach suma brutto i dane z poprzedniego miesiąca.
- **Usługa `ksef.refresh`**.

## Instalacja

### HACS

1. HACS → menu z trzema kropkami → **Niestandardowe repozytoria**.
2. Dodaj `https://github.com/bwitosze/ha-ksef`, kategoria **Integracja**.
3. Zainstaluj **KSeF - Krajowy System e-Faktur** i zrestartuj Home Assistanta.

### Ręcznie

Skopiuj katalog `custom_components/ksef/` do `config/custom_components/` i zrestartuj
Home Assistanta.

## Konfiguracja

Ustawienia → Urządzenia i usługi → **Dodaj integrację** → *KSeF*:

- **NIP** i **token KSeF** (tylko „przeglądanie faktur”, patrz wyżej).
- **Środowisko**: Produkcja, Demo albo Testowe. Token działa tylko w środowisku,
  w którym został wygenerowany.
- **Powiadomienia push**: lista rozwijana z telefonami, na których działa aplikacja
  Home Assistanta (z nazwą urządzenia), i innymi usługami `notify`. Możesz wybrać
  kilka telefonów albo wpisać usługę ręcznie. Puste pole oznacza brak pushy.

Formularz od razu próbnie loguje się do KSeF, więc zły token widać od razu.
W **Opcjach** zmienisz telefony do powiadomień, włączysz pushe o fakturach sprzedażowych
i ustawisz częstotliwość odpytywania.

## Limity KSeF

Na produkcji KSeF pozwala na **20 zapytań o listę faktur na godzinę** i 64 pobrania
XML na godzinę, liczone na parę NIP + adres IP. Dlatego:

- lista odświeża się co **15 minut**. Tyle zaleca MF, a jedno odświeżenie to dwa zapytania,
- ręczne odświeżenie działa najwyżej raz na 2 minuty,
- panel czyta lokalny cache i nie pyta KSeF przy każdym otwarciu,
- XML każdej faktury jest pobierany z KSeF tylko raz i trzymany lokalnie,
- po odpowiedzi HTTP 429 integracja nie odpytuje KSeF przez czas podany w `Retry-After`.

## Ograniczenia

- Lista obejmuje faktury według **daty wystawienia** z poprzedniego i bieżącego miesiąca.
  Faktura wystawiona wcześniej, a przesłana do KSeF później, się nie pojawi.
- Pomijane są faktury, na których występujesz jako podmiot trzeci (np. płatnik,
  dodatkowy nabywca).
- Pierwsza synchronizacja nie wysyła powiadomień, tylko zapamiętuje istniejące faktury.
- Integracja jest przeznaczona dla firm z umiarkowaną liczbą faktur. Przy kilku
  tysiącach faktur w dwóch miesiącach pełne pobranie listy przekracza godzinny limit
  KSeF i synchronizacja może się nie kończyć. Przy ponad 10 000 faktur wystawionych
  jednego dnia integracja zgłasza błąd.
- Jeśli skonfigurujesz jednocześnie wpis produkcyjny i testowy, panel pokaże je razem,
  oznaczy faktury testowe i nie wliczy ich do sum.

## Prywatność

Faktury i ich XML-e są przechowywane wyłącznie w Twoim Home Assistancie
(`.storage/ksef.*` i `.storage/ksef_xml/`). Integracja łączy się tylko z API KSeF
Ministerstwa Finansów. Pliki są dostępne wyłącznie dla zalogowanych użytkowników HA.

## Podziękowania

PDF generuje [CIRFMF/ksef-pdf-generator](https://github.com/CIRFMF/ksef-pdf-generator),
oficjalny generator wizualizacji faktur Ministerstwa Finansów (licencja MIT). Plik jest dołączony
w `custom_components/ksef/frontend/` wraz z licencją.

## Zastrzeżenie

Integracja jest **nieoficjalna** i nie jest powiązana z Ministerstwem Finansów.
Korzysta z publicznego API KSeF 2.0. Używasz jej na własną odpowiedzialność.
Nie zastępuje programu księgowego.

## Licencja

[MIT](LICENSE)
