export function isAdvancedSearchRangeOperator(operator?: string) {
  return operator === 'between' || operator === 'notBetween';
}

export function isAdvancedSearchMultiValueOperator(operator?: string) {
  return operator === 'in' || operator === 'notIn';
}

export function isAdvancedSearchNullaryOperator(operator?: string) {
  return operator === 'isNull' || operator === 'isNotNull';
}

type ValueParams = {
  inputMode: string;
  dataType?: string;
  operator: string;
};

function isNumericField(params: Pick<ValueParams, 'inputMode' | 'dataType'>) {
  return params.inputMode === 'number' || params.dataType === 'number';
}

export function getEmptyAdvancedSearchValue(params: ValueParams) {
  if (isAdvancedSearchMultiValueOperator(params.operator) && (params.inputMode === 'select' || params.inputMode === 'lookup')) {
    return [];
  }
  if (params.inputMode === 'select') {
    return null;
  }
  if (isNumericField(params)) {
    return null;
  }
  return '';
}

export function getEmptyAdvancedSearchSecondaryValue(params: Pick<ValueParams, 'inputMode' | 'dataType'>) {
  return isNumericField(params) ? null : '';
}

export function normalizeAdvancedSearchValue(params: ValueParams & { value: unknown }) {
  const { value } = params;
  if (isAdvancedSearchMultiValueOperator(params.operator) && (params.inputMode === 'select' || params.inputMode === 'lookup')) {
    if (Array.isArray(value)) {
      return value;
    }
    if (value === null || value === undefined || value === '') {
      return [];
    }
    return [value];
  }
  if (params.inputMode === 'select') {
    return value === '' || value === undefined ? null : value;
  }
  if (isNumericField(params)) {
    if (value === '' || value === undefined || value === null) {
      return null;
    }
    if (typeof value === 'number') {
      return Number.isFinite(value) ? value : null;
    }
    if (typeof value === 'string') {
      const trimmed = value.trim();
      if (!trimmed) {
        return null;
      }
      const parsed = Number(trimmed);
      return Number.isFinite(parsed) ? parsed : null;
    }
  }
  return value ?? getEmptyAdvancedSearchValue(params);
}

export function normalizeAdvancedSearchSecondaryValue(params: Pick<ValueParams, 'inputMode' | 'dataType'> & { value: unknown }) {
  const { value } = params;
  if (isNumericField(params)) {
    if (value === '' || value === undefined || value === null) {
      return null;
    }
    if (typeof value === 'number') {
      return Number.isFinite(value) ? value : null;
    }
    if (typeof value === 'string') {
      const trimmed = value.trim();
      if (!trimmed) {
        return null;
      }
      const parsed = Number(trimmed);
      return Number.isFinite(parsed) ? parsed : null;
    }
  }
  return value ?? getEmptyAdvancedSearchSecondaryValue(params);
}
