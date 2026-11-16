# Ex. 02 — hint 3 (pseudocode)

```js
export const options = {
  scenarios: {
    open: { executor: 'constant-arrival-rate', rate: Number(__ENV.RATE || 4), timeUnit: '1s',
            duration: __ENV.DURATION || '60s', preAllocatedVUs: 40, maxVUs: 240, gracefulStop: '130s' },
  },
  tags: { model: 'open', exercise: '02' },
};
```
Keep the other settings in the file (request timeout, `handleSummary`). Then `python check.py ex02`.
