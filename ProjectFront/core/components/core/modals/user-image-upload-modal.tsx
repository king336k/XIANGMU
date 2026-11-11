/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import { useDropzone } from "react-dropzone";
// plane imports
import { ACCEPTED_AVATAR_IMAGE_MIME_TYPES_FOR_REACT_DROPZONE, MAX_FILE_SIZE } from "@plane/constants";
import { Button } from "@plane/propel/button";
import { UserCirclePropertyIcon } from "@plane/propel/icons";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { EFileAssetType } from "@plane/types";
import { EModalPosition, EModalWidth, ModalCore } from "@plane/ui";
import { getAssetIdFromUrl, getFileURL, checkURLValidity } from "@plane/utils";
// services
import { FileService } from "@/services/file.service";
const fileService = new FileService();

type Props = {
  handleRemove: () => Promise<void>;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (url: string) => void | Promise<void>;
  value: string | null;
};

export const UserImageUploadModal = observer(function UserImageUploadModal(props: Props) {
  const { handleRemove, isOpen, onClose, onSuccess, value } = props;
  // states
  const [image, setImage] = useState<File | null>(null);
  const [isRemoving, setIsRemoving] = useState(false);
  const [isImageUploading, setIsImageUploading] = useState(false);

  const [previewUrl, setPreviewUrl] = useState("");
  useEffect(() => {
    if (!image) {
      setPreviewUrl("");
      return;
    }
    const url = URL.createObjectURL(image);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [image]);
  const onDrop = (acceptedFiles: File[]) => {
    if (acceptedFiles[0]) setImage(acceptedFiles[0]);
  };

  const { getRootProps, getInputProps, isDragActive, fileRejections } = useDropzone({
    onDrop,
    accept: ACCEPTED_AVATAR_IMAGE_MIME_TYPES_FOR_REACT_DROPZONE,
    maxSize: MAX_FILE_SIZE,
    multiple: false,
    disabled: isImageUploading || isRemoving,
  });

  const handleClose = () => {
    if (isImageUploading || isRemoving) return;
    setImage(null);
    onClose();
  };

  const handleSubmit = async () => {
    if (!image) return;
    setIsImageUploading(true);

    try {
      const { asset_url } = await fileService.uploadUserAsset(
        {
          entity_identifier: "",
          entity_type: EFileAssetType.USER_AVATAR,
        },
        image
      );
      await onSuccess(asset_url);
      setImage(null);
    } catch {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "头像上传失败",
        message: "请稍后重试。",
      });
    } finally {
      setIsImageUploading(false);
    }
  };

  const handleImageRemove = async () => {
    if (!value) return;
    setIsRemoving(true);
    try {
      if (checkURLValidity(value)) {
        await fileService.deleteOldUserAsset(value);
      } else {
        const assetId = getAssetIdFromUrl(value);
        await fileService.deleteUserAsset(assetId);
      }
      await handleRemove();
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: "头像移除失败，请重试" });
    } finally {
      setIsRemoving(false);
    }
  };

  return (
    <ModalCore isOpen={isOpen} handleClose={handleClose} position={EModalPosition.CENTER} width={EModalWidth.XL}>
      <div className="space-y-5 px-5 py-8 sm:p-6">
        <h3 className="text-16 leading-6 font-medium text-primary">上传图片</h3>
        <div className="space-y-3">
          <div className="flex items-center justify-center gap-3">
            <div
              {...getRootProps()}
              className={`relative grid aspect-square w-full max-w-80 cursor-pointer place-items-center rounded-lg p-12 text-center focus:ring-2 focus:ring-accent-strong focus:ring-offset-2 focus:outline-none ${
                (image === null && isDragActive) || !value
                  ? "border-2 border-dashed border-subtle hover:bg-surface-2"
                  : ""
              }`}
            >
              {image !== null || (value && value !== "") ? (
                <>
                  <button
                    type="button"
                    className="absolute top-0 right-0 z-40 translate-x-1/2 -translate-y-1/2 rounded-sm bg-surface-2 px-2 py-0.5 text-11 font-medium text-secondary"
                  >
                    编辑
                  </button>
                  <img
                    src={image ? previewUrl || undefined : value ? getFileURL(value) : ""}
                    alt="头像预览"
                    className="absolute top-0 left-0 h-full w-full rounded-md object-cover"
                  />
                </>
              ) : (
                <div>
                  <UserCirclePropertyIcon className="mx-auto h-16 w-16 text-secondary" />
                  <span className="mt-2 block text-13 font-medium text-secondary">
                    {isDragActive ? "将图片拖放到这里上传" : "点击选择或拖入图片"}
                  </span>
                </div>
              )}

              <input {...getInputProps()} aria-label="选择头像图片" />
            </div>
          </div>
          {fileRejections.length > 0 && (
            <p className="text-13 text-danger-primary">
              {fileRejections[0].errors[0].code === "file-too-large"
                ? "图片不能超过 5 MB。"
                : "请选择 JPG、PNG 或 WebP 图片。"}
            </p>
          )}
        </div>
        <p className="my-4 text-13 text-secondary">支持的文件格式：.jpeg、.jpg、.png、.webp</p>
        <div className="flex items-center justify-between">
          <Button
            variant="error-fill"
            size="lg"
            onClick={handleImageRemove}
            disabled={!value || isRemoving || isImageUploading}
          >
            {isRemoving ? "移除中" : "移除"}
          </Button>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="lg" onClick={handleClose} disabled={isImageUploading || isRemoving}>
              取消
            </Button>
            <Button
              variant="primary"
              size="lg"
              onClick={handleSubmit}
              disabled={!image || isRemoving || isImageUploading}
              loading={isImageUploading}
            >
              {isImageUploading ? "上传中" : "上传并保存"}
            </Button>
          </div>
        </div>
      </div>
    </ModalCore>
  );
});
