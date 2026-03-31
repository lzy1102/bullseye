"""
Test CLI commands
"""
import pytest
import sys
from pathlib import Path
from click.testing import CliRunner
from unittest.mock import patch, MagicMock

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
    
    def test_new_config_command(self, tmp_path):
        """Test new-config command."""
        runner = CliRunner()
        
        result = runner.invoke(cli, ['new-config', '--non-interactive'])
        
        assert result.exit_code == 0
        config_file = tmp_path / 'config.yaml'
        assert config_file.exists()
    
    def test_show_config_command(self, tmp_path, sample_config):
        """Test show-config command."""
        runner = CliRunner()
        
        with patch('bullseye.configuration.Config') as mock_config:
            mock_config.return_value = sample_config
        
        result = runner.invoke(cli, ['show-config'])
        
        assert result.exit_code == 0
        assert 'max_open_trades' in result.output
    
    def test_list_exchanges_command(self):
        """Test list-exchanges command."""
        runner = CliRunner()
        
        result = runner.invoke(cli, ['list-exchanges', '--market-type', 'crypto'])
        
        assert result.exit_code == 0
        assert 'Binance' in result.output
        assert 'OKX' in result.output
    
    def test_list_timeframes_command(self):
        """Test list-timeframes command."""
        runner = CliRunner()
        
        result = runner.invoke(cli, ['list-timeframes'])
        
        assert result.exit_code == 0
        assert '1m' in result.output
        assert '5m' in result.output
        assert '1h' in result.output
    
    def test_list_hyperoptloss_command(self):
        """Test list-hyperoptloss command."""
        runner = CliRunner()
        
        result = runner.invoke(cli, ['list-hyperoptloss'])
        
        assert result.exit_code == 0
        assert 'SharpeHyperOptLoss' in result.output
        assert 'SortinoHyperOptLoss' in result.output
    
    def test_list_data_command(self, tmp_path):
        """Test list-data command."""
        runner = CliRunner()
        
        result = runner.invoke(cli, ['list-data'])
        
        assert result.exit_code == 0
        assert 'No data files found' in result.output
    
    def test_backtesting_show_command(self, tmp_path):
        """Test backtesting-show command."""
        runner = CliRunner()
        
        result = runner.invoke(cli, ['backtesting-show'])
        
        assert result.exit_code == 0
        assert 'No backtest results found' in result.output
    
    def test_backtesting_analysis_command(self, tmp_path):
        """Test backtesting-analysis command."""
        runner = CliRunner()
        
        result = runner.invoke(cli, ['backtesting-analysis'])
        
        assert result.exit_code == 0
        assert 'No backtest results found' in result.output
    
    def test_hyperopt_list_command(self, tmp_path):
        """Test hyperopt-list command."""
        runner = CliRunner()
        
        result = runner.invoke(cli, ['hyperopt-list'])
        
        assert result.exit_code == 0
        assert 'No hyperopt results found' in result.output
    
    def test_hyperopt_show_command(self, tmp_path):
        """Test hyperopt-show command."""
        runner = CliRunner()
        
        result = runner.invoke(cli, ['hyperopt-show'])
        
        assert result.exit_code == 0
        assert 'No hyperopt results found' in result.output
    
    def test_strategy_updater_command(self, tmp_path):
        """Test strategy-updater command."""
        runner = CliRunner()
        
        result = runner.invoke(cli, ['strategy-updater', '--strategy', 'TestStrategy', '--dry-run'])
        
        assert result.exit_code == 0
        assert 'Strategy file not found' in result.output
    
    def test_show_trades_command(self):
        """Test show-trades command."""
        runner = CliRunner()
        
        result = runner.invoke(cli, ['show-trades'])
        
        assert result.exit_code == 0
        assert 'Please install required dependencies' in result.output
    
    def test_test_pairlist_command(self):
        """Test test-pairlist command."""
        runner = CliRunner()
        
        result = runner.invoke(cli, ['test-pairlist'])
        
        assert result.exit_code == 0
        assert 'No configuration loaded' in result.output
    
    def test_convert_db_command(self):
        """Test convert-db command."""
        runner = CliRunner()
        
        result = runner.invoke(cli, ['convert-db'])
        
        assert result.exit_code == 0
        assert 'Database conversion not implemented' in result.output
    
    def test_plot_dataframe_command(self, tmp_path):
        """Test plot-dataframe command."""
        runner = CliRunner()
        
        result = runner.invoke(cli, ['plot-dataframe'])
        
        assert result.exit_code == 0
        assert 'No backtest result file found' in result.output
    
    def test_plot_profit_command(self, tmp_path):
        """Test plot-profit command."""
        runner = CliRunner()
        
        result = runner.invoke(cli, ['plot-profit'])
        
        assert result.exit_code == 0
        assert 'No backtest result file found' in result.output
    
    def test_lookahead_analysis_command(self):
        """Test lookahead-analysis command."""
        runner = CliRunner()
        
        result = runner.invoke(cli, ['lookahead-analysis', '--strategy', 'TestStrategy'])
        
        assert result.exit_code == 0
        assert 'Analyzing' in result.output
        assert 'No lookahead bias detected' in result.output
    
    def test_recursive_analysis_command(self):
        """Test recursive-analysis command."""
        runner = CliRunner()
        
        result = runner.invoke(cli, ['recursive-analysis', '--strategy', 'TestStrategy'])
        
        assert result.exit_code == 0
        assert 'Analyzing' in result.output
        assert 'No recursive bias detected' in result.output
    
    def test_webserver_command(self):
        """Test webserver command."""
        runner = CliRunner()
        
        result = runner.invoke(cli, ['webserver'])
        
        assert result.exit_code == 0
        assert 'Starting Bullseye API Server' in result.output
