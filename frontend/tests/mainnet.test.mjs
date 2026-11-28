// Montos de la página /mainnet (src/lib/mainnet.ts): sin float, 7 decimales.

import assert from "node:assert/strict";
import { test } from "node:test";

import { formatUsdc, parseUsdc, MAINNET } from "../src/lib/mainnet.ts";

test("parseUsdc convierte texto a unidades sin float", () => {
  assert.equal(parseUsdc("0.02"), 200000n);
  assert.equal(parseUsdc("1"), 10000000n);
  assert.equal(parseUsdc("0.0000001"), 1n);
  assert.equal(parseUsdc(" 12.5 "), 125000000n);
  for (const malo of ["", "abc", "0.12345678", "-1", "1e3", "1,5"]) assert.throws(() => parseUsdc(malo), malo);
});

test("formatUsdc es el inverso de parseUsdc", () => {
  for (const t of ["0.02", "1", "0.0000001", "12.5"]) assert.equal(formatUsdc(parseUsdc(t)), t);
});

test("la configuración apunta a la red pública, al XLM nativo y al USDC de Circle", () => {
  assert.equal(MAINNET.passphrase, "Public Global Stellar Network ; September 2015");
  assert.equal(MAINNET.usdcSac, "CCW67TSZV3SSS2HXMBQ5JFGCKJNXKZM7UQUWUZPUTHXSTZLEO7SJMI75");
  assert.equal(MAINNET.token.sac, "CAS3J7GYLGXMF6TDJBBYYSE3HQ6BBSMLNUQ34T6TZMYMW2EVH34XOWMA");
  assert.match(MAINNET.explorer, /explorer\/public$/);
});
