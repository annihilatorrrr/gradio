import io
import sys
import unittest
import unittest.mock as mock
from contextlib import contextmanager

import mlflow
import pytest
import requests
import wandb
from fastapi.testclient import TestClient

from gradio.blocks import Blocks
from gradio.interface import Interface, TabbedInterface, close_all, os
from gradio.layouts import TabItem, Tabs
from gradio.utils import assert_configs_are_equivalent_besides_ids

os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"


@contextmanager
def captured_output():
    new_out, new_err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = new_out, new_err
        yield sys.stdout, sys.stderr
    finally:
        sys.stdout, sys.stderr = old_out, old_err


class TestInterface(unittest.TestCase):
    def test_close(self):
        io = Interface(lambda input: None, "textbox", "label")
        _, local_url, _ = io.launch(prevent_thread_lock=True)
        response = requests.get(local_url)
        self.assertEqual(response.status_code, 200)
        io.close()
        with self.assertRaises(Exception):
            response = requests.get(local_url)

    def test_close_all(self):
        interface = Interface(lambda input: None, "textbox", "label")
        interface.close = mock.MagicMock()
        close_all()
        interface.close.assert_called()

    def test_no_input_or_output(self):
        with self.assertRaises(TypeError):
            Interface(lambda x: x, examples=1234)

    def test_examples_valid_path(self):
        path = os.path.join(
            os.path.dirname(__file__), "../gradio/test_data/flagged_with_log"
        )
        interface = Interface(lambda x: 3 * x, "number", "number", examples=path)
        dataset_check = any(
            c["type"] == "dataset"
            for c in interface.get_config_file()["components"]
        )

        self.assertTrue(dataset_check)

    def test_test_launch(self):
        with captured_output() as (out, err):
            prediction_fn = lambda x: x
            prediction_fn.__name__ = "prediction_fn"
            interface = Interface(prediction_fn, "textbox", "label")
            interface.test_launch()
            output = out.getvalue().strip()
            self.assertEqual(output, "Test launch: prediction_fn()... PASSED")

    @mock.patch("time.sleep")
    def test_block_thread(self, mock_sleep):
        with self.assertRaises(KeyboardInterrupt):
            with captured_output() as (out, _):
                mock_sleep.side_effect = KeyboardInterrupt()
                interface = Interface(lambda x: x, "textbox", "label")
                interface.launch(prevent_thread_lock=False)
                output = out.getvalue().strip()
                self.assertEqual(
                    output, "Keyboard interruption in main thread... closing server."
                )

    @mock.patch("gradio.utils.colab_check")
    def test_launch_colab_share(self, mock_colab_check):
        mock_colab_check.return_value = True
        interface = Interface(lambda x: x, "textbox", "label")
        _, _, share_url = interface.launch(prevent_thread_lock=True)
        self.assertIsNotNone(share_url)
        interface.close()

    @mock.patch("gradio.utils.colab_check")
    @mock.patch("gradio.networking.setup_tunnel")
    def test_launch_colab_share_error(self, mock_setup_tunnel, mock_colab_check):
        mock_setup_tunnel.side_effect = RuntimeError()
        mock_colab_check.return_value = True
        interface = Interface(lambda x: x, "textbox", "label")
        _, _, share_url = interface.launch(prevent_thread_lock=True)
        self.assertIsNone(share_url)
        interface.close()

    def test_interface_representation(self):
        prediction_fn = lambda x: x
        prediction_fn.__name__ = "prediction_fn"
        repr = str(Interface(prediction_fn, "textbox", "label")).split("\n")
        self.assertTrue(prediction_fn.__name__ in repr[0])
        self.assertEqual(len(repr[0]), len(repr[1]))

    @pytest.mark.asyncio
    async def test_interface_none_interp(self):
        interface = Interface(lambda x: x, "textbox", "label", interpretation=[None])
        scores = (await interface.interpret(["quickest brown fox"]))[0][
            "interpretation"
        ]
        self.assertIsNone(scores)

    @mock.patch("webbrowser.open")
    def test_interface_browser(self, mock_browser):
        interface = Interface(lambda x: x, "textbox", "label")
        interface.launch(inbrowser=True, prevent_thread_lock=True)
        mock_browser.assert_called_once()
        interface.close()

    def test_examples_list(self):
        examples = ["test1", "test2"]
        interface = Interface(lambda x: x, "textbox", "label", examples=examples)
        interface.launch(prevent_thread_lock=True)
        self.assertEqual(len(interface.examples_handler.examples), 2)
        self.assertEqual(len(interface.examples_handler.examples[0]), 1)
        interface.close()

    @mock.patch("IPython.display.display")
    def test_inline_display(self, mock_display):
        interface = Interface(lambda x: x, "textbox", "label")
        interface.launch(inline=True, prevent_thread_lock=True)
        mock_display.assert_called_once()
        interface.launch(inline=True, prevent_thread_lock=True)
        self.assertEqual(mock_display.call_count, 2)
        interface.close()

    @mock.patch("comet_ml.Experiment")
    def test_integration_comet(self, mock_experiment):
        experiment = mock_experiment()
        experiment.log_text = mock.MagicMock()
        experiment.log_other = mock.MagicMock()
        interface = Interface(lambda x: x, "textbox", "label")
        interface.launch(prevent_thread_lock=True)
        interface.integrate(comet_ml=experiment)
        experiment.log_text.assert_called_with(f"gradio: {interface.local_url}")
        interface.share_url = "tmp"  # used to avoid creating real share links.
        interface.integrate(comet_ml=experiment)
        experiment.log_text.assert_called_with(f"gradio: {interface.share_url}")
        self.assertEqual(experiment.log_other.call_count, 2)
        interface.share_url = None
        interface.close()

    def test_integration_mlflow(self):
        mlflow.log_param = mock.MagicMock()
        interface = Interface(lambda x: x, "textbox", "label")
        interface.launch(prevent_thread_lock=True)
        interface.integrate(mlflow=mlflow)
        mlflow.log_param.assert_called_with(
            "Gradio Interface Local Link", interface.local_url
        )
        interface.share_url = "tmp"  # used to avoid creating real share links.
        interface.integrate(mlflow=mlflow)
        mlflow.log_param.assert_called_with(
            "Gradio Interface Share Link", interface.share_url
        )
        interface.share_url = None
        interface.close()

    def test_integration_wandb(self):
        with captured_output() as (out, err):
            wandb.log = mock.MagicMock()
            wandb.Html = mock.MagicMock()
            interface = Interface(lambda x: x, "textbox", "label")
            interface.width = 500
            interface.height = 500
            interface.integrate(wandb=wandb)

            self.assertEqual(
                out.getvalue().strip(),
                "The WandB integration requires you to `launch(share=True)` first.",
            )
            interface.share_url = "tmp"
            interface.integrate(wandb=wandb)
            wandb.log.assert_called_once()

    @mock.patch("requests.post")
    def test_integration_analytics(self, mock_post):
        mlflow.log_param = mock.MagicMock()
        interface = Interface(lambda x: x, "textbox", "label")
        interface.analytics_enabled = True
        interface.integrate(mlflow=mlflow)
        mock_post.assert_called_once()


class TestTabbedInterface(unittest.TestCase):
    def test_tabbed_interface_config_matches_manual_tab(self):
        interface1 = Interface(lambda x: x, "textbox", "textbox")
        interface2 = Interface(lambda x: x, "image", "image")

        with Blocks(mode="tabbed_interface") as demo:
            with Tabs():
                with TabItem(label="tab1"):
                    interface1.render()
                with TabItem(label="tab2"):
                    interface2.render()

        interface3 = Interface(lambda x: x, "textbox", "textbox")
        interface4 = Interface(lambda x: x, "image", "image")
        tabbed_interface = TabbedInterface([interface3, interface4], ["tab1", "tab2"])

        self.assertTrue(
            assert_configs_are_equivalent_besides_ids(
                demo.get_config_file(), tabbed_interface.get_config_file()
            )
        )


class TestDeprecatedInterface(unittest.TestCase):
    def test_deprecation_notice(self):
        with self.assertWarns(Warning):
            _ = Interface(lambda x: x, "textbox", "textbox", verbose=True)


class TestInterfaceInterpretation(unittest.TestCase):
    def test_interpretation_from_interface(self):
        def quadratic(num1: float, num2: float) -> float:
            return 3 * num1**2 + num2

        iface = Interface(
            fn=quadratic,
            inputs=["number", "number"],
            outputs="number",
            interpretation="default",
        )

        app, _, _ = iface.launch(prevent_thread_lock=True)
        client = TestClient(app)

        btn = next(
            c["id"]
            for c in iface.config["components"]
            if c["props"].get("value") == "Interpret"
        )
        fn_index = next(
            i
            for i, d in enumerate(iface.config["dependencies"])
            if d["targets"] == [btn]
        )

        response = client.post(
            "/api/predict/", json={"fn_index": fn_index, "data": [10, 50, 350]}
        )
        self.assertTrue(response.json()["data"][0]["interpretation"] is not None)
        iface.close()
        close_all()


if __name__ == "__main__":
    unittest.main()
