export default function Toggle({
  checked,
  onChange,
  disabled,
  label
}: {
  checked: boolean;
  onChange: () => void;
  disabled?: boolean;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={onChange}
      disabled={disabled}
      className={`relative w-9 h-5 rounded-full shrink-0 transition-colors disabled:opacity-40 ${
        checked ? 'bg-accent' : 'bg-base-700'
      }`}
    >
      <span
        className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full transition-transform ${
          checked ? 'translate-x-4 bg-base-950' : 'translate-x-0 bg-ink'
        }`}
      />
    </button>
  );
}
