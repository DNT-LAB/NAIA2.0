import assert from 'node:assert/strict';

import {
  autocompleteInsertPolicyForRow,
  canSelectAutocompleteRow,
  firstDefaultAutocompleteIndexForRows,
} from '../../ui/remote_web/js/features/tagAssist.mjs';

const translationHint = {
  tag: 'raise one arms',
  candidateType: 'translation_hint',
  insertPolicy: 'manual',
  candidate: {
    type: 'translation_hint',
    source: 'translation_fallback',
    insertPolicy: 'manual',
  },
};
const promptPhrase = {
  tag: 'arms raised',
  candidateType: 'prompt_phrase',
  insertPolicy: 'default',
  candidate: {
    type: 'prompt_phrase',
    source: 'phrase_normalizer',
    insertPolicy: 'default',
  },
};

assert.equal(autocompleteInsertPolicyForRow(translationHint), 'manual');
assert.equal(canSelectAutocompleteRow(translationHint), false);
assert.equal(canSelectAutocompleteRow(translationHint, {manual: true}), true);
assert.equal(canSelectAutocompleteRow(promptPhrase), true);
assert.equal(firstDefaultAutocompleteIndexForRows([translationHint, promptPhrase]), 1);
assert.equal(firstDefaultAutocompleteIndexForRows([{disabled: true}, translationHint]), -1);
assert.equal(autocompleteInsertPolicyForRow({_wc_type: 'preset_status'}), 'none');
