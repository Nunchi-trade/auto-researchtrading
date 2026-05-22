"""
MiroFish REST API client.

Wraps the MiroFish backend API (default port 5001) for creating projects,
building knowledge graphs, running simulations, and extracting results.
"""

import json
import time
import sys
import requests


class MiroFishError(Exception):
    """Error from MiroFish API."""
    def __init__(self, message, status_code=None, response_body=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class MiroFishClient:
    def __init__(self, base_url="http://localhost:5001", debug=False):
        self.base_url = base_url.rstrip("/")
        self.debug = debug
        self.session = requests.Session()

    def _request(self, method, path, **kwargs):
        url = f"{self.base_url}{path}"
        if self.debug:
            print(f"  [MiroFish] {method} {url}", file=sys.stderr)
        try:
            resp = self.session.request(method, url, timeout=60, **kwargs)
        except requests.ConnectionError:
            raise MiroFishError(
                f"Cannot connect to MiroFish at {self.base_url}. "
                "Is it running? Try: bash equities/mirofish/setup.sh"
            )
        except requests.Timeout:
            raise MiroFishError(f"Request to {url} timed out")

        if self.debug and resp.status_code >= 400:
            print(f"  [MiroFish] {resp.status_code}: {resp.text[:500]}", file=sys.stderr)

        if resp.status_code >= 400:
            raise MiroFishError(
                f"API error {resp.status_code}: {resp.text[:300]}",
                status_code=resp.status_code,
                response_body=resp.text,
            )
        return resp.json() if resp.content else {}

    def _get(self, path, **kwargs):
        return self._request("GET", path, **kwargs)

    def _post(self, path, **kwargs):
        return self._request("POST", path, **kwargs)

    # -----------------------------------------------------------------------
    # Health
    # -----------------------------------------------------------------------

    def health_check(self):
        """Check if MiroFish is running. Returns True if healthy."""
        try:
            resp = self._get("/health")
            return resp.get("status") == "ok"
        except MiroFishError:
            return False

    # -----------------------------------------------------------------------
    # Graph API
    # -----------------------------------------------------------------------

    def create_project(self, name, seed_docs):
        """
        Create a project and upload seed documents.
        seed_docs: list of strings (document contents)
        Returns project_id.
        """
        # Create project via ontology generation with inline docs
        resp = self._post("/api/graph/ontology/generate", json={
            "project_name": name,
            "documents": seed_docs,
        })
        return resp.get("project_id", resp.get("id"))

    def build_graph(self, project_id, poll_interval=5, timeout=300):
        """
        Build knowledge graph from project. Polls until complete.
        Returns graph_id.
        """
        resp = self._post("/api/graph/build", json={"project_id": project_id})
        task_id = resp.get("task_id")
        if not task_id:
            return resp.get("graph_id")

        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self._get(f"/api/graph/task/{task_id}")
            if status.get("status") == "completed":
                return status.get("graph_id", status.get("result", {}).get("graph_id"))
            if status.get("status") == "failed":
                raise MiroFishError(f"Graph build failed: {status}")
            time.sleep(poll_interval)

        raise MiroFishError(f"Graph build timed out after {timeout}s")

    # -----------------------------------------------------------------------
    # Simulation API
    # -----------------------------------------------------------------------

    def create_simulation(self, graph_id, config=None):
        """
        Create a new simulation instance.
        config: optional dict with platform, agent_count, rounds, etc.
        Returns simulation_id.
        """
        payload = {"graph_id": graph_id}
        if config:
            payload.update(config)
        resp = self._post("/api/simulation/create", json=payload)
        return resp.get("simulation_id", resp.get("id"))

    def prepare_simulation(self, sim_id, poll_interval=5, timeout=300):
        """Prepare simulation (entity reading, profile generation). Polls until ready."""
        self._post("/api/simulation/prepare", json={"simulation_id": sim_id})

        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self._post("/api/simulation/prepare/status",
                                json={"simulation_id": sim_id})
            if status.get("status") == "completed":
                return status
            if status.get("status") == "failed":
                raise MiroFishError(f"Simulation preparation failed: {status}")
            time.sleep(poll_interval)

        raise MiroFishError(f"Simulation preparation timed out after {timeout}s")

    def run_simulation(self, sim_id, poll_interval=5, timeout=600):
        """Start and run simulation. Polls until complete. Returns final status."""
        self._post("/api/simulation/start", json={"simulation_id": sim_id})

        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self._get(f"/api/simulation/{sim_id}/run-status")
            if status.get("status") in ("completed", "stopped"):
                return status
            if status.get("status") == "failed":
                raise MiroFishError(f"Simulation failed: {status}")
            time.sleep(poll_interval)

        raise MiroFishError(f"Simulation timed out after {timeout}s")

    def get_simulation(self, sim_id):
        """Get current simulation state."""
        return self._get(f"/api/simulation/{sim_id}")

    def get_timeline(self, sim_id):
        """Get round-by-round timeline summaries."""
        return self._get(f"/api/simulation/{sim_id}/timeline")

    def get_agent_actions(self, sim_id):
        """Get all agent actions from the simulation."""
        return self._get(f"/api/simulation/{sim_id}/actions")

    def get_agent_stats(self, sim_id):
        """Get per-agent statistics."""
        return self._get(f"/api/simulation/{sim_id}/agent-stats")

    def get_posts(self, sim_id):
        """Get all posts from the simulation."""
        return self._get(f"/api/simulation/{sim_id}/posts")

    # -----------------------------------------------------------------------
    # Interviews
    # -----------------------------------------------------------------------

    def interview_agents(self, sim_id, question):
        """Interview all agents with a question. Returns dict of responses."""
        resp = self._post("/api/simulation/interview/all", json={
            "simulation_id": sim_id,
            "question": question,
        })
        return resp

    def interview_batch(self, sim_id, agent_ids, question):
        """Interview specific agents."""
        resp = self._post("/api/simulation/interview/batch", json={
            "simulation_id": sim_id,
            "agent_ids": agent_ids,
            "question": question,
        })
        return resp

    # -----------------------------------------------------------------------
    # Reports
    # -----------------------------------------------------------------------

    def generate_report(self, sim_id, poll_interval=10, timeout=300):
        """Generate analysis report. Polls until complete. Returns markdown."""
        resp = self._post("/api/report/generate", json={"simulation_id": sim_id})
        report_id = resp.get("report_id")
        if not report_id:
            return resp.get("report", "")

        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self._post("/api/report/generate/status",
                                json={"report_id": report_id})
            if status.get("status") == "completed":
                report = self._get(f"/api/report/{report_id}")
                return report.get("content", report.get("markdown", str(report)))
            if status.get("status") == "failed":
                raise MiroFishError(f"Report generation failed: {status}")
            time.sleep(poll_interval)

        raise MiroFishError(f"Report generation timed out after {timeout}s")

    # -----------------------------------------------------------------------
    # Full pipeline
    # -----------------------------------------------------------------------

    def run_scenario(self, name, seed_docs, agent_count=50, rounds=10):
        """
        Run a complete scenario pipeline: project → graph → simulation → results.
        Returns (simulation_id, timeline, agent_actions).
        """
        print(f"  [MiroFish] Creating project: {name}")
        project_id = self.create_project(name, seed_docs)

        print(f"  [MiroFish] Building knowledge graph...")
        graph_id = self.build_graph(project_id)

        print(f"  [MiroFish] Creating simulation ({agent_count} agents, {rounds} rounds)...")
        sim_id = self.create_simulation(graph_id, {
            "agent_count": agent_count,
            "max_rounds": rounds,
        })

        print(f"  [MiroFish] Preparing simulation...")
        self.prepare_simulation(sim_id)

        print(f"  [MiroFish] Running simulation...")
        self.run_simulation(sim_id)

        print(f"  [MiroFish] Extracting results...")
        timeline = self.get_timeline(sim_id)
        actions = self.get_agent_actions(sim_id)

        return sim_id, timeline, actions


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test MiroFish connection")
    parser.add_argument("--url", default="http://localhost:5001")
    parser.add_argument("--test", action="store_true", help="Run connection test")
    args = parser.parse_args()

    client = MiroFishClient(base_url=args.url, debug=True)

    if args.test:
        if client.health_check():
            print("MiroFish is healthy!")
        else:
            print("MiroFish is NOT reachable.")
            sys.exit(1)
