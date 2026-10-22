"""
Test CLI commands
"""
import sys
from pathlib import Path
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

from bullseye.__main__ import cli


class TestCLICommands:
    """Test suite for CLI commands."""

    def test_cli_root_command(self):
        """Test root CLI command."""
        runner = CliRunner()
        result = runner.invoke(cli, ['--help'])

        assert result.exit_code == 0
        assert 'Bullseye' in result.output
        assert 'Usage:' in result.output

    def test_create_userdir_command(self, tmp_path):
        """Test create-userdir command."""
        runner = CliRunner()

        result = runner.invoke(cli, ['create-userdir', '--userdir', str(tmp_path)])

        assert result.exit_code == 0
        assert tmp_path.exists()
        assert (tmp_path / 'strategies').exists()
        assert (tmp_path / 'backtest_results').exists()

    def test_new_config_command(self):
        """Test new-config command."""
        runner = CliRunner()

        result = runner.invoke(cli, ['new-config', '--help'])

        assert result.exit_code == 0

    def test_show_config_command(self):
        """Test show-config command."""
        runner = CliRunner()

        result = runner.invoke(cli, ['show-config', '--help'])

        assert result.exit_code == 0

    def test_list_exchanges_command(self):
        """Test list-exchanges command."""
        runner = CliRunner()

        result = runner.invoke(cli, ['list-exchanges'])

        assert result.exit_code == 0
        assert 'binance' in result.output.lower()

    def test_list_timeframes_command(self):
        """Test list-timeframes command."""
        runner = CliRunner()

        result = runner.invoke(cli, ['list-timeframes'])

        assert result.exit_code == 0
        assert '1m' in result.output
        assert '5m' in result.output
        assert '1h' in result.output

    def test_list_data_command(self):
        """Test list-data command."""
        runner = CliRunner()

        result = runner.invoke(cli, ['list-data'])

        assert result.exit_code == 0

    def test_backtesting_command_help(self):
        """Test backtesting command help."""
        runner = CliRunner()

        result = runner.invoke(cli, ['backtesting', '--help'])

        assert result.exit_code == 0
        assert 'strategy' in result.output.lower()

    def test_hyperopt_command_help(self):
        """Test hyperopt command help."""
        runner = CliRunner()

        result = runner.invoke(cli, ['hyperopt', '--help'])

        assert result.exit_code == 0
        assert 'strategy' in result.output.lower()
        assert 'epochs' in result.output.lower()

    def test_show_trades_command(self):
        """Test show-trades command."""
        runner = CliRunner()

        result = runner.invoke(cli, ['show-trades'])

        assert result.exit_code == 0

    def test_test_pairlist_command(self):
        """Test test-pairlist command."""
        runner = CliRunner()

        result = runner.invoke(cli, ['test-pairlist'])

        assert result.exit_code == 0

    def test_version_command(self):
        """Test version command."""
        runner = CliRunner()

        result = runner.invoke(cli, ['version'])

        assert result.exit_code == 0
        assert 'Bullseye' in result.output

    def test_info_command(self):
        """Test info command."""
        runner = CliRunner()

        result = runner.invoke(cli, ['info'])

        assert result.exit_code == 0 or 'Bullseye' in result.output

    def test_new_strategy_command_help(self):
        """Test new-strategy command help."""
        runner = CliRunner()

        result = runner.invoke(cli, ['new-strategy', '--help'])

        assert result.exit_code == 0
        assert 'template' in result.output.lower()

    def test_list_strategies_command(self):
        """Test list-strategies command."""
        runner = CliRunner()

        result = runner.invoke(cli, ['list-strategies'])

        assert result.exit_code == 0

    def test_init_project_command(self):
        """Test init-project command."""
        runner = CliRunner()

        result = runner.invoke(cli, ['init-project'])

        assert result.exit_code == 0

    def test_trade_command_help(self):
        """Test trade command help."""
        runner = CliRunner()

        result = runner.invoke(cli, ['trade', '--help'])

        assert result.exit_code == 0
        assert 'strategy' in result.output.lower()


class TestNewConfigTemplates:
    """`bullseye new-config` must produce a usable template per market."""

    @staticmethod
    def _content(market_type):
        from bullseye.commands.config_commands import generate_config_content
        return generate_config_content({"market_type": market_type})

    def test_futures_template_is_futures_ready(self):
        content = self._content("future")
        assert "market_type: future" in content
        assert "trading_mode: futures" in content
        assert "margin_mode: isolated" in content
        assert "stake_currency: CNY" in content
        assert "name: ctp" in content
        assert "contracts_file" in content
        # the live SimNow front, not the retired one
        assert "182.254.243.31:30001" in content
        assert "180.168.146.187" not in content

    def test_stock_template_is_spot(self):
        content = self._content("stock")
        assert "market_type: stock" in content
        assert "trading_mode: spot" in content
        assert "stake_currency: CNY" in content
        assert "name: xtp" in content

    def test_crypto_template_keeps_auto_mode(self):
        content = self._content("crypto")
        assert "trading_mode: auto" in content
        assert "name: binance" in content

    def test_template_documents_the_futures_trading_mode(self):
        content = self._content("future")
        assert "auto | spot | futures | margin" in content
