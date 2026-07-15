type LocaleOptions = {
  locale: string;
};

type CurrencyOptions = LocaleOptions & {
  currency: string;
};

type DateTimeOptions = LocaleOptions & {
  timezone: string;
};

const requireValue = (value: string, name: string): string => {
  const normalized = value.trim();
  if (!normalized) throw new RangeError(`${name} is required`);
  return normalized;
};

const requireLocale = (locale: string): string => {
  const normalized = requireValue(locale, "locale");
  if (Intl.NumberFormat.supportedLocalesOf([normalized]).length !== 1) {
    throw new RangeError(`Unsupported locale: ${normalized}`);
  }
  return normalized;
};

export const formatNumber = (value: number, options: LocaleOptions): string => {
  if (!Number.isFinite(value)) throw new RangeError("number must be finite");
  return new Intl.NumberFormat(requireLocale(options.locale)).format(value);
};

export const formatCurrency = (
  value: number,
  options: CurrencyOptions,
): string => {
  if (!Number.isFinite(value)) throw new RangeError("currency value must be finite");
  const locale = requireLocale(options.locale);
  const currency = requireValue(options.currency, "currency");
  if (!/^[A-Z]{3}$/.test(currency)) {
    throw new RangeError("currency must be an uppercase ISO 4217 code");
  }
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    currencyDisplay: "symbol",
  }).format(value);
};

export const formatDateTime = (
  value: string | number | Date,
  options: DateTimeOptions,
): string => {
  const locale = requireLocale(options.locale);
  const timezone = requireValue(options.timezone, "timezone");
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) throw new RangeError("date must be valid");

  return new Intl.DateTimeFormat(locale, {
    timeZone: timezone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(date);
};
