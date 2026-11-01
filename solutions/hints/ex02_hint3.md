# Ćw. 02 — podpowiedź 3 (pseudokod)

```js
export const options = {
  scenarios: {
    otwarty: { executor: 'constant-arrival-rate', rate: Number(__ENV.RATE || 4), timeUnit: '1s',
               duration: __ENV.CZAS || '60s', preAllocatedVUs: 40, maxVUs: 240, gracefulStop: '130s' },
  },
  tags: { model: 'otwarty', cwiczenie: '02' },
};
```
Zachowaj pozostałe ustawienia pliku (timeout żądań, `handleSummary`). Potem `python check.py ex02`.
