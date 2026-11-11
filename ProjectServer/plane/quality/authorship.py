# SPDX-License-Identifier: AGPL-3.0-only
from rest_framework import serializers


def authored_metadata(obj):
    author = getattr(obj, "created_by", None)
    return {
        "created_by_id": str(author.id) if author else None,
        "created_by_name": (author.display_name or author.first_name or author.username) if author else "未记录",
        "created_at": obj.created_at,
    }


class AuthoredRecordSerializer(serializers.ModelSerializer):
    def to_representation(self, instance):
        data = super().to_representation(instance)
        data.update({key: value for key, value in authored_metadata(instance).items() if key != "created_at"})
        from .numbering import metadata

        data.update(metadata(instance))
        return data
