# KSeF dla Home Assistanta

Nieoficjalna integracja Home Assistanta z **Krajowym Systemem e-Faktur (KSeF 2.0)**.
Pokazuje Twoje faktury zakupowe i sprzedażowe w osobnym panelu w menu bocznym
i wysyła push, gdy wpadnie nowa faktura zakupowa.

To nie jest program księgowy. Integracja daje tylko podgląd listy faktur
z poprzedniego i bieżącego miesiąca oraz pobieranie plików.

## Funkcje

- **Panel „KSeF” w menu bocznym**: faktury zakupowe i sprzedażowe, przełącznik
  poprzedni/bieżący miesiąc, kwoty netto i brutto, sumy, ręczne odświeżanie.
- **Pobieranie PDF i XML** każdej faktury. PDF generuje w przeglądarce oficjalny
  generator wizualizacji Ministerstwa Finansów, z kodem QR weryfikacji.
- **Powiadomienia push** o nowych fakturach zakupowych (opcjonalnie także sprzedażowych)
  przez dowolną usługę `notify`, np. aplikację mobilną Home Assistanta.
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

## Token KSeF

Integracja loguje się tokenem KSeF. Token generujesz raz:

1. Wejdź na **https://ap.ksef.mf.gov.pl** (Aplikacja Podatnika KSeF) i zaloguj się
   przez login.gov.pl: profil zaufany, mObywatel, bank albo e-dowód.
2. Wybierz kontekst swojego **NIP-u**.
3. **Tokeny → Generuj token**. Nadaj nazwę, np. „Home Assistant”, i zaznacz
   **tylko „przeglądanie faktur”**. Inne uprawnienia nie są potrzebne.
4. Kliknij **Generuj token**, a gdy proces się zakończy, **Kopiuj**. Token jest pokazywany
   **tylko raz** i zawiera znaki `|`, więc skopiuj go w całości.

Token nie wygasa, dopóki go nie unieważnisz (Tokeny → Lista tokenów). Gdy KSeF
go odrzuci, Home Assistant poprosi o nowy.

## Konfiguracja

Ustawienia → Urządzenia i usługi → **Dodaj integrację** → *KSeF*:

- **NIP** i **token KSeF**.
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
