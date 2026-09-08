---
name: summarize
description: Use when the user is stopping work on an unfinished feature and wants its state saved so they can resume days later - "podsumuj sesje", "zapisz stan prac", "summarize the session", "robie przerwe", "wracam za kilka dni", "save where we are". Also use when a session ends with work mid-flight, or when the user comes back and asks what was going on with a branch.
---

# Podsumowanie sesji

Utrzymuje **jeden żywy dokument na gałąź** ze stanem prac, żeby po kilku dniach przerwy
dało się wrócić do roboty w minutę — bez czytania całej rozmowy od nowa.

**Zasada:** dokument opisuje **stan**, nie przebieg. „Gdzie jesteśmy i co dalej", a nie
„najpierw zrobiliśmy X, potem Y". Przebieg trafia wyłącznie do dziennika na końcu, w 3–5
punktach.

Pisz **po polsku**. Nazwy plików, funkcji, gałęzi, komend i commitów zostają oryginalne.

## Plik

`.workbench/sessions/<gałąź>.md`, ukośniki zamienione na `-`:
`feature/agentic-part-2` → `.workbench/sessions/feature-agentic-part-2.md`

Jeśli `.workbench/` nie istnieje — utwórz je i sprawdź, czy `.gitignore` zawiera
`.workbench`. Jeśli nie zawiera, dopisz i powiedz o tym użytkownikowi. Te notatki nigdy
nie trafiają do repo.

## Krok 1 — zbierz fakty z gita

Zanim napiszesz jedno zdanie:

```bash
git branch --show-current
git status --short
git log --oneline -15
git diff --stat
git diff --cached --stat
```

**Reguła dowodu:** pozycja trafia do „Zrobione" tylko wtedy, gdy widać ją w commicie na
gałęzi albo w diffie roboczym. Rzeczy zaplanowane, zaproponowane, cofnięte lub tylko
omówione idą do „Zostało" albo „Uwagi i decyzje". Nie uruchamiaj testów ani linterów.

## Krok 2 — napisz dokument

Dokładnie te sekcje, w tej kolejności:

| Sekcja | Zawiera | Limit |
|---|---|---|
| Nagłówek + meta | Nazwa funkcjonalności, gałąź, data ostatniej sesji, ostatni commit | 2 linie |
| `## Cel` | Co budujemy i **po co**. Stabilne między sesjami — przepisz tylko, gdy cel naprawdę się zmienił | 2–4 zdania |
| `## Następny krok` | Jedna konkretna rzecz do zrobienia po powrocie: plik, miejsce, czynność. Plus linia o niezacommitowanej robocie | 3–5 linii |
| `## Zrobione` | Ukończone pozycje z odnośnikiem do commita lub pliku | po 1 linii |
| `## Zostało` | Niezrobione pozycje, najważniejsze na górze | po 1 linii |
| `## Uwagi i decyzje` | Podjęte decyzje z uzasadnieniem, blokery, ślepe uliczki (żeby ich nie powtarzać) | po 1–2 linie |
| `## Dziennik sesji` | Wpis na sesję, dopisywany na dole | 3–5 punktów |

Cały plik ≤ 120 linii. Zero ścian tekstu — punkty, nie akapity.

## Krok 3 — zaktualizuj, nie nadpisuj

Plik już istnieje? Przeczytaj go i:

1. Zostaw `## Cel` bez zmian, chyba że cel prac faktycznie się przesunął.
2. Przepisz `Następny krok`, `Zrobione`, `Zostało`, `Uwagi i decyzje` na aktualną prawdę —
   pozycje z „Zostało" potwierdzone commitem przenieś do „Zrobione".
3. **Dopisz** wpis do dziennika. Nie kasuj poprzednich. Ponowne wywołanie tego samego dnia
   aktualizuje wpis z tą datą, nie tworzy drugiego.
4. Trzymaj maksymalnie 8 wpisów w dzienniku — najstarsze usuwaj.

Na koniec wypisz w czacie ścieżkę pliku i samą treść sekcji „Następny krok".

## Przykład

```markdown
# Agentowy czat nad pipeline'em wideo

**Gałąź:** feature/agentic-part-2 · **Sesja:** 2026-09-03 · **HEAD:** 6057c61

## Cel
Zamiana sztywnego `URL → Notion` na wielokrokowego agenta, który sam decyduje, które
narzędzia odpalić i do której bazy Notion pisać. Ta gałąź dokłada ścieżkę odczytu wideo
(transkrypty w bazie + streaming czatu) na fundamencie z PR #20.

## Następny krok
> Dopisać obsługę `UsageLimitExceeded` w `orchestrator.py:142` — dziś leci 500 zamiast 429.
> Test odtwarzający jest już w `tests/unit/test_orchestrator.py::test_usage_limit`, na
> czerwono.

Niezacommitowane: `src/webtonotion/services/orchestrator.py` (+40/−12), reszta czysta.

## Zrobione
- [x] Narzędzia ścieżki odczytu wideo + zapis transkryptów (`6057c61`)
- [x] Streaming odpowiedzi czatu przez SSE (`6057c61`)

## Zostało
- [ ] Mapowanie `UsageLimitExceeded` → HTTP 429
- [ ] Bump wersji w `pyproject.toml` przed PR-em (wymagane przez `pr-check.yml`)

## Uwagi i decyzje
- Historia rozmowy ucinana na granicy tury, nie tokena — ucinanie w środku tury psuło
  parowanie tool-call/tool-result.
- Odrzucone: cache transkryptów w Redis. Za duży narzut na jedną instancję, `FileCacheService`
  wystarcza.

---
## Dziennik sesji

### 2026-09-03
- Doszły narzędzia odczytu wideo i storage transkryptów, 38 plików, commit `6057c61`.
- Zaczęta obsługa limitów użycia — test napisany, implementacja niedokończona.
```

## Typowe błędy

| Błąd | Zamiast tego |
|---|---|
| Kronika „zrobiliśmy X, potem Y" | Stan: co działa, czego brakuje, co dalej |
| „Kontynuować prace nad narzędziami" | Konkretny plik, linia i czynność |
| „Zrobione", bo tak ustaliliśmy w rozmowie | „Zrobione" tylko z pokryciem w commicie lub diffie |
| Nadpisanie całego pliku | Cel i dziennik zostają, reszta się aktualizuje |
| Wrzucanie każdego wywołania narzędzia | 3–5 punktów w dzienniku, reszta do kosza |
| Pominięcie odrzuconych pomysłów | Ślepe uliczki do „Uwagi i decyzje" — inaczej powtórzysz je za tydzień |

## Kiedy nie używać

Do chronologicznej pamięci między sesjami służy plugin `remember` (`.remember/`). Ten skill
robi co innego: jeden dokument stanu na funkcjonalność, czytany przy powrocie do gałęzi.
Nie używaj go do domykania pracy, która właśnie idzie do PR-a — tam opis zmian należy do
opisu PR-a.
