"""Standalone entry point for converting OCP usage exports."""

from kubernetes_resource_optimizer.utils.ocp_usage_to_csv import main

if __name__ == "__main__":
    raise SystemExit(main())
