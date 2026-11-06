export function extractionFor(document) {
  return document?.extraction || document || {};
}

export function fieldsFor(document) {
  return Object.entries(extractionFor(document))
    .filter(
      ([key, value]) =>
        key.endsWith("_data") && value && typeof value === "object",
    )
    .flatMap(([, block]) =>
      Object.entries(block).map(([name, field]) => ({
        name,
        ...(field && typeof field === "object" ? field : { value: field }),
      })),
    );
}
