// Valida el banco de datos sin dependencias.
import { readFileSync } from "node:fs";
import { catalogo } from "../data/catalogo.mjs";

const errores = [];
for (const key of ["nombre", "remoto", "tipo", "medido", "paleta"]) {
  if (!(key in catalogo)) errores.push(`falta ${key}`);
}
if (!/^#[0-9a-f]{6}$/i.test(catalogo.paleta?.accent ?? "")) errores.push("acento inválido");
const json = JSON.parse(readFileSync(new URL("../data/catalogo.json", import.meta.url), "utf8"));
if (json.nombre !== catalogo.nombre) errores.push("json y mjs no coinciden");

if (errores.length) {
  console.error("FALLA\n" + errores.join("\n"));
  process.exit(1);
}
console.log(`OK  ${catalogo.nombre}: ${catalogo.medido.archivos} archivos`);
