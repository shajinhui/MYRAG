import { useState, useRef, useCallback, memo } from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import { Upload, FileUp, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { FADE_FAST, MOTION_INSTANT, SPRING_CONTROL } from "@/lib/motion";

const ACCEPTED_TYPES = ".pdf,.txt,.docx,.md,.pptx";
const ACCEPTED_EXTENSIONS = new Set(["pdf", "txt", "docx", "md", "pptx"]);
const MAX_SIZE_MB = 50;

interface UploadZoneProps {
  onUpload: (file: File) => void;
  isUploading?: boolean;
  compact?: boolean;
  /** 始终可见的迷你拖放区域 */
  mini?: boolean;
}

export const UploadZone = memo(function UploadZone({ onUpload, isUploading, compact, mini }: UploadZoneProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const reduceMotion = useReducedMotion();

  const validateFile = useCallback((file: File): string | null => {
    const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
    if (!ACCEPTED_EXTENSIONS.has(ext)) return `不支持的格式：.${ext}`;
    if (file.size > MAX_SIZE_MB * 1024 * 1024) return `文件过大（最大 ${MAX_SIZE_MB}MB）`;
    return null;
  }, []);

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (!files) return;
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const error = validateFile(file);
        if (error) {
          setValidationError(error);
          continue;
        }
        setValidationError(null);
        onUpload(file);
      }
    },
    [onUpload, validateFile]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles]
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
  }, []);

  if (mini) {
    return (
      <>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_TYPES}
          multiple
          onChange={(e) => { handleFiles(e.target.files); if (inputRef.current) inputRef.current.value = ""; }}
          className="hidden"
        />
        <motion.div
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onClick={() => inputRef.current?.click()}
          animate={isDragOver && !reduceMotion ? { scale: 1.01 } : { scale: 1 }}
          transition={reduceMotion ? MOTION_INSTANT : SPRING_CONTROL}
          role="button"
          tabIndex={0}
          aria-label="上传文档"
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              inputRef.current?.click();
            }
          }}
          className={cn(
            "ui-upload-zone h-full rounded-xl border border-dashed cursor-pointer transition-colors duration-200",
            "flex flex-col items-center justify-center",
            isDragOver
              ? "border-primary bg-primary/5"
              : "border-border hover:border-primary/50 hover:bg-muted/30",
            isUploading && "opacity-60 pointer-events-none"
          )}
        >
          <AnimatePresence mode="wait">
            {validationError ? (
              <motion.div
                key="error"
                initial={{ opacity: 0, y: reduceMotion ? 0 : 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={reduceMotion ? MOTION_INSTANT : FADE_FAST}
                className="flex max-w-[220px] flex-col items-center px-3 text-center"
                role="status"
              >
                <AlertCircle className="mb-1 h-5 w-5 text-destructive" />
                <p className="text-[11px] font-medium text-destructive">{validationError}</p>
                <p className="mt-0.5 text-[9px] text-muted-foreground">点击重新选择</p>
              </motion.div>
            ) : isDragOver ? (
              <motion.div
                key="drop"
                initial={{ opacity: 0, scale: reduceMotion ? 1 : 0.96 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: reduceMotion ? 1 : 0.96 }}
                transition={reduceMotion ? MOTION_INSTANT : FADE_FAST}
                className="flex flex-col items-center"
              >
                <FileUp className="w-6 h-6 text-primary mb-1" />
                <p className="text-xs font-medium text-primary">拖放文件到此处</p>
              </motion.div>
            ) : (
              <motion.div
                key="idle"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={reduceMotion ? MOTION_INSTANT : FADE_FAST}
                className="flex flex-col items-center"
              >
                <Upload className={cn("w-6 h-6 text-muted-foreground mb-1", isUploading && "animate-pulse")} />
                <p className="text-xs font-medium">
                  {isUploading ? "上传中..." : "拖放文件或点击上传"}
                </p>
                <p className="text-[10px] text-muted-foreground/60 mt-0.5">
                  PDF、DOCX、PPTX、TXT、MD（最大 {MAX_SIZE_MB}MB）
                </p>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      </>
    );
  }

  if (compact) {
    return (
      <>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_TYPES}
          multiple
          onChange={(e) => { handleFiles(e.target.files); if (inputRef.current) inputRef.current.value = ""; }}
          className="hidden"
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={isUploading}
          className={cn(
            "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium",
            "bg-primary text-primary-foreground hover:bg-primary/90",
            "disabled:opacity-50 disabled:pointer-events-none transition-colors"
          )}
        >
          <Upload className={cn("w-4 h-4", isUploading && "animate-pulse")} />
          {isUploading ? "上传中..." : "上传"}
        </button>
      </>
    );
  }

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED_TYPES}
        multiple
        onChange={(e) => { handleFiles(e.target.files); if (inputRef.current) inputRef.current.value = ""; }}
        className="hidden"
      />
      <motion.div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => inputRef.current?.click()}
        animate={isDragOver && !reduceMotion ? { scale: 1.01 } : { scale: 1 }}
        transition={reduceMotion ? MOTION_INSTANT : SPRING_CONTROL}
        role="button"
        tabIndex={0}
        aria-label="上传文档"
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        className={cn(
          "relative rounded-lg border-2 border-dashed cursor-pointer transition-colors duration-200",
          "flex flex-col items-center justify-center py-8 px-4",
          isDragOver
            ? "border-primary bg-primary/5"
            : "border-border hover:border-primary/50 hover:bg-muted/30",
          isUploading && "opacity-60 pointer-events-none"
        )}
      >
        <AnimatePresence mode="wait">
          {validationError ? (
            <motion.div
              key="error"
              initial={{ opacity: 0, y: reduceMotion ? 0 : 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={reduceMotion ? MOTION_INSTANT : FADE_FAST}
              className="flex flex-col items-center text-center"
              role="status"
            >
              <AlertCircle className="w-7 h-7 text-destructive mb-2" />
              <p className="text-sm font-medium text-destructive">{validationError}</p>
              <p className="text-xs text-muted-foreground mt-1">点击重新选择文件</p>
            </motion.div>
          ) : isDragOver ? (
            <motion.div
              key="drop"
              initial={{ opacity: 0, scale: reduceMotion ? 1 : 0.96 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: reduceMotion ? 1 : 0.96 }}
              transition={reduceMotion ? MOTION_INSTANT : FADE_FAST}
              className="flex flex-col items-center"
            >
              <FileUp className="w-8 h-8 text-primary mb-2" />
              <p className="text-sm font-medium text-primary">拖放文件到此处</p>
            </motion.div>
          ) : (
            <motion.div
              key="idle"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={reduceMotion ? MOTION_INSTANT : FADE_FAST}
              className="flex flex-col items-center"
            >
              <Upload className="w-8 h-8 text-muted-foreground mb-2" />
              <p className="text-sm font-medium">
                {isUploading ? "上传中..." : "拖放文件或点击上传"}
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                PDF、DOCX、PPTX、TXT、MD（最大 {MAX_SIZE_MB}MB）
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </>
  );
});
