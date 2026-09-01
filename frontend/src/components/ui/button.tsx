import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "ui-button inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[10px] border text-sm font-semibold outline-none disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-45",
  {
    variants: {
      variant: {
        default:
          "border-primary/35 bg-primary text-primary-foreground shadow-[0_1px_2px_rgba(0,0,0,0.12),inset_0_1px_0_rgba(255,255,255,0.16)] hover:brightness-[1.04]",
        destructive:
          "border-destructive/35 bg-destructive text-destructive-foreground shadow-[0_1px_2px_rgba(0,0,0,0.12),inset_0_1px_0_rgba(255,255,255,0.12)] hover:brightness-[1.04]",
        outline:
          "border-border bg-card/55 text-foreground shadow-[0_1px_2px_rgba(0,0,0,0.06),inset_0_1px_0_rgba(255,255,255,0.05)] hover:bg-secondary/85",
        secondary:
          "border-border/75 bg-secondary text-secondary-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] hover:brightness-[1.05]",
        ghost:
          "border-transparent bg-transparent text-muted-foreground shadow-none hover:bg-secondary/70 hover:text-foreground",
        link:
          "border-transparent bg-transparent text-primary shadow-none underline-offset-4 hover:underline",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-9 px-3",
        lg: "h-11 rounded-xl px-6",
        icon: "h-10 w-10 p-0",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => {
    return (
      <button
        className={cn(buttonVariants({ variant, size, className }))}
        data-variant={variant ?? "default"}
        data-size={size ?? "default"}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
