import type { LucideIcon } from "lucide-react";
import { HelpTip } from "./ui";

/** A row of radio buttons that looks like a segmented control. `help` puts the explanation under a "?" beside the name. */
export function Choice<T extends string>({ name, legend, hint, help, value, choices, onChange }: { name: string; legend: string; hint?: string; help?: string; value: T; choices: { value: T; label: string; icon?: LucideIcon }[]; onChange: (value: T) => void }) {
  return (
    <fieldset>
      <legend className="field-label flex items-center gap-2">{legend}{help && <HelpTip label={legend}>{help}</HelpTip>}</legend>
      {hint && <p className="text-xs text-ink-subtle">{hint}</p>}
      <div className="segmented mt-2">
        {choices.map(({ value: option, label, icon: Icon }) => (
          <label key={option} className={`filter-tab inline-flex cursor-pointer items-center gap-2 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-forest ${value === option ? "filter-tab-active" : ""}`}>
            <input type="radio" name={name} value={option} checked={value === option} onChange={() => onChange(option)} className="sr-only" />
            {Icon && <Icon size={15} aria-hidden="true" />}{label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
