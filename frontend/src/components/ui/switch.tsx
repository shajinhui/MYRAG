import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export interface SwitchProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  onCheckedChange?: (checked: boolean) => void;
}

const Switch = forwardRef<HTMLInputElement, SwitchProps>(
  ({ className, checked, onCheckedChange, onChange, ...props }, ref) => {
    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      onChange?.(e);
      onCheckedChange?.(e.target.checked);
    };

    return (
      <label className="relative inline-flex cursor-pointer items-center">
        <input
          type="checkbox"
          className="ui-switch-input peer sr-only"
          ref={ref}
          checked={checked}
          onChange={handleChange}
          {...props}
        />
        <span
          className={cn(
            "ui-switch-track relative h-[22px] w-[38px] rounded-full",
            className
          )}
        >
          <span className="ui-switch-thumb absolute left-0.5 top-0.5 h-[18px] w-[18px] rounded-full" />
        </span>
      </label>
    );
  }
);
Switch.displayName = "Switch";

export { Switch };
