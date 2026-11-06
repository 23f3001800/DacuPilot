import test from "node:test";
import assert from "node:assert/strict";
import { extractionFor, fieldsFor } from "../src/lib/documents.js";

test("document review reads the nested pipeline response", () => {
  const document = {
    document_type: "PAN_CARD",
    extraction: {
      text_medium: "PRINTED",
      pan_data: {
        pan_number: {
          value: "ABCDE1234F",
          final_field_score: 0.8,
          requires_human_review: true,
        },
      },
      system_evaluation_matrix: {
        final_routing_decision: "HUMAN_REVIEWS_REQUIRED",
      },
    },
  };
  assert.equal(fieldsFor(document)[0].value, "ABCDE1234F");
  assert.equal(fieldsFor(document)[0].requires_human_review, true);
  assert.equal(
    extractionFor(document).system_evaluation_matrix.final_routing_decision,
    "HUMAN_REVIEWS_REQUIRED",
  );
});

test("document review also supports saved flat extractions", () => {
  const document = { pan_data: { full_name: { value: "Alex Example" } } };
  assert.equal(fieldsFor(document)[0].name, "full_name");
  assert.equal(fieldsFor(document)[0].value, "Alex Example");
});

test("failed pages produce an empty field table", () => {
  assert.deepEqual(
    fieldsFor({ document_type: "UNKNOWN", error: "Needs review" }),
    [],
  );
});
